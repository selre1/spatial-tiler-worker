# -*- coding: utf-8 -*-
import logging
import time
import numpy as np
import ifcopenshell
from ..Color import ColorConfig
from ..Common import Feature, FeatureList, TreeWithChildrenAndParent
from ifcopenshell import geom
from py3dtiles.tileset.extension import BatchTableHierarchy
import ifcopenshell.util.element


class IfcObjectGeom(Feature):
    def __init__(self, ifcObject, ifcGroup="None", ifcSpace="None", with_BTH=False):
        super().__init__(ifcObject.GlobalId)
        self.ifcClass = ifcObject.is_a()
        self.material = None
        # Per-material geometry parts for a single IFC object (strategy 1)
        # Filled in parse_geom when IfcOpenShell provides material_ids.
        self.material_parts_local = []  # [{'local_mid': int, 'material': pygltflib.Material, 'triangles': list}]
        self.material_parts = []        # [{'material_index': int, 'triangles': list}]
        self.ifcGroup = ifcGroup
        self.ifcSpace = ifcSpace
        self.setBatchTableData(ifcObject, ifcGroup, ifcSpace)
        self.has_geom = self.parse_geom(ifcObject)
        if with_BTH:
            self.getParentsInIfc(ifcObject)

    def hasGeom(self):
        return self.has_geom

    def set_triangles(self, triangles):
        self.geom.triangles[0] = triangles

    def getParentsInIfc(self, ifcObject):
        self.parents = list()
        while ifcObject:
            ifcParent = ifcopenshell.util.element.get_container(ifcObject)

            if not ifcParent:
                if hasattr(ifcObject, "Decomposes"):
                    if len(ifcObject.Decomposes) > 0:
                        ifcParent = ifcObject.Decomposes[0].RelatingObject
                if hasattr(ifcObject, "VoidsElements"):
                    if len(ifcObject.VoidsElements) > 0:
                        ifcParent = ifcObject.VoidsElements[0].RelatingBuildingElement
            if ifcParent:
                self.parents.append({'id': ifcParent.GlobalId, 'ifcClass': ifcParent.is_a()})
            ifcObject = ifcParent

    def computeCenter(self, pointList):
        center = np.array([0.0, 0.0, 0.0])
        for point in pointList:
            center += np.array([point[0], point[1], 0])
        return center / len(pointList)

    def setBatchTableData(self, ifcObject, ifcGroup, ifcSpace):
        properties = list()
        for prop in ifcObject.IsDefinedBy:
            if hasattr(prop, 'RelatingPropertyDefinition'):
                if prop.RelatingPropertyDefinition.is_a('IfcPropertySet'):
                    props = list()
                    props.append(prop.RelatingPropertyDefinition.Name)
                    for propSet in prop.RelatingPropertyDefinition.HasProperties:
                        if propSet.is_a('IfcPropertySingleValue'):
                            if propSet.NominalValue:
                                props.append([propSet.Name, propSet.NominalValue.wrappedValue])
                    properties.append(props)
        batch_table_data = {
            'classe': self.ifcClass,
            'group': ifcGroup,
            'space': ifcSpace,
            'name': ifcObject.Name,
            'properties': properties
        }
        super().set_batchtable_data(batch_table_data)

    def getIfcClasse(self):
        return self.ifcClasse

    def parse_geom(self, ifcObject):
        if not (ifcObject.Representation):
            return False

        try:
            settings = geom.settings()
            settings.set(settings.USE_WORLD_COORDS, True)  # Translates and rotates the points to their world coordinates
            if hasattr(settings, 'SEW_SHELLS'):
                settings.set(settings.SEW_SHELLS, True)
            settings.set(settings.APPLY_DEFAULT_MATERIALS, False)
            shape = geom.create_shape(settings, ifcObject)
        except RuntimeError:
            logging.error("Error while creating geom with IfcOpenShell")
            return False

        vertexList = np.reshape(np.array(shape.geometry.verts), (-1, 3))
        indexList = np.reshape(np.array(shape.geometry.faces), (-1, 3))

        # Build triangles and (when available) keep per-material parts.
        # IfcOpenShell may provide:
        # - shape.geometry.materials     : list of materials
        # - shape.geometry.material_ids  : per-face material id (same length as indexList)
        local_mats = list(shape.geometry.materials) if getattr(shape.geometry, "materials", None) else []
        mat_ids = getattr(shape.geometry, "material_ids", None)
        mat_ids_arr = None
        if mat_ids is not None:
            try:
                mat_ids_arr = np.array(mat_ids, dtype=np.int32).reshape(-1)
            except Exception:
                mat_ids_arr = None
        if mat_ids_arr is None or mat_ids_arr.size != len(indexList):
            mat_ids_arr = np.zeros(len(indexList), dtype=np.int32)

        if indexList.size == 0:
            logging.error("Error while creating geom : No triangles found")
            return False

        triangles = []
        face_indices_by_mid = {}

        for fi, index in enumerate(indexList):
            triangle = []
            for i in range(0, 3):
                # We store each position for each triangles, as GLTF expects
                triangle.append(vertexList[index[i]])
            triangles.append(triangle)

            mid = int(mat_ids_arr[fi])
            face_indices_by_mid.setdefault(mid, []).append(fi)

        # Create per-part materials (colors) when materials exist.
        self.material_parts_local = []
        self.material_parts = []
        if local_mats:
            for mid, face_idx in face_indices_by_mid.items():
                src_mat = local_mats[mid] if 0 <= mid < len(local_mats) else local_mats[0]
                color = [src_mat.diffuse.r(), src_mat.diffuse.g(), src_mat.diffuse.b(), 1]
                mat = ColorConfig().to_material(color)
                self.material_parts_local.append({"local_mid": int(mid), "material": mat, "face_indices": face_idx})
            # Backward compatibility: keep self.material as the first part material
            self.material = self.material_parts_local[0]["material"]
        else:
            self.material = None

        self.geom.triangles.append(triangles)

        self.set_box()

        return True

    def get_obj_id(self):
        return super().get_id()

    def set_obj_id(self, id):
        return super().set_id(id)


class IfcObjectsGeom(FeatureList):
    """
        A decorated list of FeatureList type objects.
    """

    def __init__(self, objs=None):
        super().__init__(objs)

    @staticmethod
    def create_batch_table_extension(extension_name, ids, objects):
        if extension_name == "batch_table_hierarchy":
            resulting_bth = BatchTableHierarchy()
            bth_classes = {}
            hierarchy = TreeWithChildrenAndParent()
            parents = dict()

            for obj in objects:
                if obj.ifcClass not in bth_classes:
                    bth_classes[obj.ifcClass] = resulting_bth.add_class(obj.ifcClass, {'GUID'})
                if obj.parents:
                    hierarchy.addNodeToParent(obj.id, obj.parents[0]['id'])
                i = 1
                for parent in obj.parents:
                    if i < len(obj.parents):
                        hierarchy.addNodeToParent(obj.parents[i - 1]['id'], obj.parents[i]['id'])
                    if parent['id'] not in parents:
                        parents[parent['id']] = parent
                    if parent['ifcClass'] not in bth_classes:
                        bth_classes[parent['ifcClass']] = resulting_bth.add_class(parent['ifcClass'], {'GUID'})
                    i += 1

            objectPosition = {}
            for i, obj in enumerate(objects):
                objectPosition[obj.id] = i
            for i, parent in enumerate(parents):
                objectPosition[parent] = i + len(objects)

            for obj in objects:
                obj_class = bth_classes[obj.ifcClass]
                obj_class.add_instance(
                    {
                        'GUID': obj.id
                    },
                    [objectPosition[id_parent] for id_parent in hierarchy.getParents(obj.id)]
                )
            for parent in parents.items():
                parent_class = bth_classes[parent[1]["ifcClass"]]
                parent_class.add_instance(
                    {
                        'GUID': parent[1]["id"]
                    },
                    [objectPosition[id_parent] for id_parent in hierarchy.getParents(parent[1]["id"])]
                )

            return resulting_bth
        else:
            return None

    @staticmethod
    def retrievObjByType(path_to_file, with_BTH):
        """
        :param path: a path to a directory

        :return: a list of Obj.
        """
        ifc_file = ifcopenshell.open(path_to_file)

        buildings = ifc_file.by_type('IfcBuilding')
        dictObjByType = dict()
        _ = ifc_file.by_type('IfcSlab')
        i = 1

        for building in buildings:
            elements = ifcopenshell.util.element.get_decomposition(building)
            nb_element = str(len(elements))
            logging.info(nb_element + " elements to parse in building :" + building.GlobalId)
            for element in elements:
                start_time = time.time()
                logging.info(str(i) + " / " + nb_element)
                logging.info("Parsing " + element.GlobalId + ", " + element.is_a())
                obj = IfcObjectGeom(element, with_BTH=with_BTH)
                if obj.hasGeom():
                    if not (element.is_a() + building.GlobalId in dictObjByType):
                        dictObjByType[element.is_a() + building.GlobalId] = IfcObjectsGeom()
                    # Strategy 1: one IFC object may contain multiple materials (e.g., sign board + letters).
                    if getattr(obj, "material_parts_local", None):
                        obj.material_parts = []
                        for part in obj.material_parts_local:
                            mat_index = dictObjByType[element.is_a() + building.GlobalId].get_material_index(part["material"])
                            obj.material_parts.append({"material_index": mat_index, "face_indices": part["face_indices"]})
                        obj.material_index = obj.material_parts[0]["material_index"] if obj.material_parts else 0
                    elif obj.material:
                        obj.material_index = dictObjByType[element.is_a() + building.GlobalId].get_material_index(obj.material)
                    else:
                        obj.material_index = 0
                    dictObjByType[element.is_a() + building.GlobalId].append(obj)
                logging.info("--- %s seconds ---" % (time.time() - start_time))
                i = i + 1
        return dictObjByType

    @staticmethod
    def retrievObjByGroup(path_to_file, with_BTH):
        """
        :param path: a path to a directory

        :return: a list of Obj.
        """
        ifc_file = ifcopenshell.open(path_to_file)

        elements = ifc_file.by_type('IfcElement')
        nb_element = str(len(elements))
        logging.info(nb_element + " elements to parse")

        groups = ifc_file.by_type("IFCRELASSIGNSTOGROUP")
        if not groups:
            logging.info("No IfcGroup found")

        dictObjByGroup = dict()
        for group in groups:
            dictObjByGroup[group.RelatingGroup.Name] = IfcObjectsGeom()
            for element in group.RelatedObjects:
                if element.is_a('IfcElement'):
                    logging.info("Parsing " + element.GlobalId + ", " + element.is_a())
                    elements.remove(element)
                    obj = IfcObjectGeom(element, ifcGroup=group.RelatingGroup.Name, with_BTH=with_BTH)
                    if obj.hasGeom():
                        dictObjByGroup[element.ifcGroup].append(obj)
                    # Strategy 1: one IFC object may contain multiple materials (e.g., sign board + letters).
                    if getattr(obj, "material_parts_local", None):
                        obj.material_parts = []
                        for part in obj.material_parts_local:
                            mat_index = dictObjByGroup[element.ifcGroup].get_material_index(part["material"])
                            obj.material_parts.append({"material_index": mat_index, "face_indices": part["face_indices"]})
                        obj.material_index = obj.material_parts[0]["material_index"] if obj.material_parts else 0
                    elif obj.material:
                        obj.material_index = dictObjByGroup[element.ifcGroup].get_material_index(obj.material)
                    else:
                        obj.material_index = 0

        dictObjByGroup["None"] = IfcObjectsGeom()
        for element in elements:
            logging.info("Parsing " + element.GlobalId + ", " + element.is_a())
            obj = IfcObjectGeom(element, with_BTH=with_BTH)
            if obj.hasGeom():
                dictObjByGroup[obj.ifcGroup].append(obj)
            # Strategy 1: one IFC object may contain multiple materials (e.g., sign board + letters).
            if getattr(obj, "material_parts_local", None):
                obj.material_parts = []
                for part in obj.material_parts_local:
                    mat_index = dictObjByGroup[obj.ifcGroup].get_material_index(part["material"])
                    obj.material_parts.append({"material_index": mat_index, "face_indices": part["face_indices"]})
                obj.material_index = obj.material_parts[0]["material_index"] if obj.material_parts else 0
            elif obj.material:
                obj.material_index = dictObjByGroup[obj.ifcGroup].get_material_index(obj.material)
            else:
                obj.material_index = 0

        return dictObjByGroup

    @staticmethod
    def retrievObjBySpace(path_to_file, with_BTH):
        """
        :param path: a path to an ifc
        :return: a list of obj grouped by IfcSpace
        """
        ifc_file = ifcopenshell.open(path_to_file)

        elements = ifc_file.by_type('IfcElement')
        nb_element = str(len(elements))
        logging.info(nb_element + " elements to parse")

        dictObjByIfcSpace = dict()
        # init a group for objects not in any IfcSpace
        dictObjByIfcSpace["None"] = IfcObjectsGeom()
        ifc_spaces = ifc_file.by_type("IFCSPACE")
        logging.info(f"Found {len(ifc_spaces)} IfcSpace.")

        # init a group for each IfcSpace
        for s in ifc_spaces:
            dictObjByIfcSpace[s.id()] = IfcObjectsGeom()
            obj = IfcObjectGeom(s, with_BTH=with_BTH)
            if obj.hasGeom():
                # we put the ifcspace as any other geom in its tile
                dictObjByIfcSpace[s.id()].append(obj)
                # Strategy 1: one IFC object may contain multiple materials (e.g., sign board + letters).
            if getattr(obj, "material_parts_local", None):
                obj.material_parts = []
                for part in obj.material_parts_local:
                    mat_index = dictObjByIfcSpace[s.id()].get_material_index(part["material"])
                    obj.material_parts.append({"material_index": mat_index, "face_indices": part["face_indices"]})
                obj.material_index = obj.material_parts[0]["material_index"] if obj.material_parts else 0
            elif obj.material:
                obj.material_index = dictObjByIfcSpace[s.id()].get_material_index(obj.material)
            else:
                obj.material_index = 0

        # Iterate over all elements, and attribute them to spaces when we can
        for e in elements:
            container = ifcopenshell.util.element.get_container(e)
            if container is None or container.is_a() != 'IfcSpace':
                ifcspace_id_key = 'None'
            else:
                ifcspace_id_key = container.id()
            obj = IfcObjectGeom(e, with_BTH=with_BTH, ifcSpace=ifcspace_id_key)
            if obj.hasGeom():
                group = dictObjByIfcSpace[ifcspace_id_key]
                group.append(obj)
                # Strategy 1: one IFC object may contain multiple materials (e.g., sign board + letters).
            if getattr(obj, "material_parts_local", None):
                obj.material_parts = []
                for part in obj.material_parts_local:
                    mat_index = group.get_material_index(part["material"])
                    obj.material_parts.append({"material_index": mat_index, "face_indices": part["face_indices"]})
                obj.material_index = obj.material_parts[0]["material_index"] if obj.material_parts else 0
            elif obj.material:
                obj.material_index = group.get_material_index(obj.material)
            else:
                obj.material_index = 0
        return dictObjByIfcSpace
