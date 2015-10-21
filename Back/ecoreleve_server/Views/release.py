from pyramid.view import view_config
from ..Models import (
    DBSession,
    Individual,
    Station,
    Observation,
    ProtocoleType,
    Sensor,
    Equipment,
    IndividualList
    )
from ecoreleve_server.GenericObjets.FrontModules import FrontModules
from ecoreleve_server.GenericObjets import ListObjectWithDynProp
import transaction
import json, itertools
from datetime import datetime
import datetime as dt
import pandas as pd
import numpy as np
from sqlalchemy import select, and_,cast, DATE,func,desc,join
from sqlalchemy.orm import aliased
from pyramid.security import NO_PERMISSION_REQUIRED
from traceback import print_exc
from collections import OrderedDict
import pandas as pd
from collections import Counter

prefix = 'release/'

@view_config(route_name= prefix+'individuals/action', renderer='json', request_method = 'GET', permission = NO_PERMISSION_REQUIRED)
def actionOnStations(request):
    print ('\n*********************** Action **********************\n')
    dictActionFunc = {
    # 'count' : count_,
    'getFields': getFields,
    'getFilters': getFilters
    }
    actionName = request.matchdict['action']
    return dictActionFunc[actionName](request)

def getFilters (request):
    ModuleType = 'IndivReleaseGrid'
    filtersList = Individual().GetFilters(ModuleType)
    filters = {}
    for i in range(len(filtersList)) :
        filters[str(i)] = filtersList[i]
    transaction.commit()
    return filters

def getFields(request) :

    ModuleType = request.params['name']
    if ModuleType == 'default' :
        ModuleType = 'IndivReleaseGrid'
    cols = Individual().GetGridFields(ModuleType)
    cols.append({
        'name' :'import',
        'label' : 'import',
        'renderable': True,
        'editable': True,
        'cell' : 'select-row',
        'headerCell': 'select-all'
        })
    transaction.commit()
    return cols

@view_config(route_name= prefix+'individuals', renderer='json', request_method = 'GET', permission = NO_PERMISSION_REQUIRED)
def searchIndiv(request):
    data = request.params.mixed()
    print('*********data*************')
    print(data)
    searchInfo = {}
    searchInfo['criteria'] = []
    if 'criteria' in data: 
        data['criteria'] = json.loads(data['criteria'])
        if data['criteria'] != {} :
            searchInfo['criteria'] = [obj for obj in data['criteria'] if obj['Value'] != str(-1) ]

    try:
        searchInfo['order_by'] = json.loads(data['order_by'])
    except:
        searchInfo['order_by'] = ['ID:desc']
    criteria = [
    {
    'Column': 'LastImported',
    'Operator' : '=',
    'Value' : True
    }]
    searchInfo['criteria'].extend(criteria)

    ModuleType = 'IndivFilter'
    moduleFront  = DBSession.query(FrontModules).filter(FrontModules.Name == ModuleType).one()
    listObj = IndividualList(moduleFront)
    dataResult = listObj.GetFlatDataList(searchInfo)

    countResult = listObj.count(searchInfo)
    result = [{'total_entries':countResult}]
    result.append(dataResult)
    transaction.commit()
    return result


@view_config(route_name= prefix+'individuals', renderer='json', request_method = 'POST', permission = NO_PERMISSION_REQUIRED)
def releasePost(request):

    data = request.params.mixed()
    sta_id = int(data['StationID'])
    indivList = json.loads(data['IndividualList'])
    curStation = DBSession.query(Station).get(sta_id)
    # releaseMethod = data['releaseMethod']
    releaseMethod = None
    taxon = indivList[0]['Species']
    print(indivList)
    class protocolList :

        def __init__(self,typeID):
            self.typeID = typeID
            self.list_ = []

        def new(self):
            return Observation(FK_ProtocoleType=self.typeID)

        def getList(self):
            return self.list_

        def add(self,obs):
            self.list_.append(obs)

    protoTypes = pd.DataFrame(DBSession.execute(select([ProtocoleType])).fetchall(), columns = ProtocoleType.__table__.columns.keys())
    vertebrateGrpID = int(protoTypes.loc[protoTypes['Name'] == 'Vertebrate group','ID'].values[0])
    vertebrateIndID = int(protoTypes.loc[protoTypes['Name'] == 'Vertebrate individual','ID'].values[0])
    biometryID = int(protoTypes.loc[protoTypes['Name'] == 'Bird Biometry','ID'].values[0])
    releaseGrpID = int(protoTypes.loc[protoTypes['Name'] == 'Release Group','ID'].values[0])
    releaseIndID = int(protoTypes.loc[protoTypes['Name'] == 'Release Individual','ID'].values[0])
    equipmentIndID = int(protoTypes.loc[protoTypes['Name'] == 'Individual equipment','ID'].values[0])

    vertebrateGrp = Observation(FK_ProtocoleType=vertebrateGrpID)
    releaseGrp = Observation(FK_ProtocoleType=releaseGrpID)

    vertebrateIndList = protocolList(vertebrateIndID)
    biometryList = protocolList(biometryID)
    releaseIndList = protocolList(releaseIndID)
    equipmentIndList = protocolList(equipmentIndID)

    binaryDict = {
    9: 'nb_adult_indeterminate',
    10: 'nb_adult_male',
    12: 'nb_adult_female',
    17: 'nb_juvenile_indeterminate',
    18: 'nb_juvenile_male',
    20: 'nb_juvenile_female',
    33: 'nb_indeterminate',
    36: 'nb_indeterminate',
    34: 'nb_indeterminate'
    }

    def MoF_AoJ(obj):
        #### binary ponderation female : 4, male :2 , indeterminateSex : 1, adult:8, juvenile : 16, indeterminateAge : 32
        curSex = None
        curAge = None
        binP = 0

        if obj['Sex'] is not None and obj['Sex'].lower() == 'male':
            curSex = 'male'
            binP += 2
        elif obj['Sex'] is not None and obj['Sex'].lower() == 'female':
            curSex = 'female'
            binP += 4
        else : 
            curSex == 'Indeterminate'
            binP += 1

        if obj['Age'] is not None and obj['Age'].lower() == 'Adult':
            curAge = 'Adult'
            binP += 8
        elif obj['Age'] is not None and obj['Age'].lower() == 'juvenile':
            curAge = 'Juvenile'
            binP += 16
        else : 
            curAge == 'Indeterminate'
            binP += 32
        return binaryDict[binP]

    binList = []

    for indiv in indivList: 
        curIndiv = DBSession.query(Individual).get(indiv['ID'])
        curIndiv.LoadNowValues()
        curIndiv.UpdateFromJson(indiv)

        indiv['FK_Individual'] = indiv['ID']
        indiv['FK_Station'] = curStation.ID

        binList.append(MoF_AoJ(indiv))
        # here add info for Vetebrate individual protocol
        curVertebrateInd = vertebrateIndList.new()
        curVertebrateInd.UpdateFromJson(indiv)

        # here add info for Bird Biometry protocol
        curBiometry = biometryList.new()
        curBiometry.UpdateFromJson(indiv)
        biometryList.add(curBiometry)

        # here add info for Release Individual protocol
        curReleaseInd = releaseIndList.new()
        curReleaseInd.UpdateFromJson(indiv)
        releaseIndList.add(curReleaseInd)

        # here add info for Individual Equipment protocol
        # if isinstance(indiv['FK_Sensor'], int):
        #     curEquipmentInd = equipmentIndList.new()
        #     curEquipmentInd.UpdateFromJson(indiv)
        #     equipmentIndList.add(curEquipmentInd)

    
    dictVertGrp = dict(Counter(binList))
    dictVertGrp['taxon'] = taxon
    print(dictVertGrp)
    vertebrateGrp.UpdateFromJson(dictVertGrp)
    releaseGrp.UpdateFromJson({'taxon':taxon, 'release_method':releaseMethod})

    vertebrateGrp.Observation_children.extend(vertebrateIndList.getList())
    releaseGrp.Observation_children.extend(releaseIndList.getList())

    listObs = []
    listObs.append(vertebrateGrp)
    listObs.append(releaseGrp)
    listObs.extend(biometryList.getList())
    # finally append all Protocols to Station
    print(listObs)
    # curStation.Observations

    # transaction.commit()

    return {}
    # return {'release':len(releaseIndList.getList())}