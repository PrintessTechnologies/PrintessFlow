# Copyright (c) Printess Technologies
# Replaces the frozen MaterialBrandsModel with one that shows ALL materials
# regardless of approximate_diameter — so syringe materials with different
# barrel diameters are never hidden by Cura's compatibility filter.

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtQml import QQmlEngine

from UM.Qt.ListModel import ListModel
from UM.Logger import Logger
from cura.Machines.Models.BaseMaterialsModel import BaseMaterialsModel

import cura.CuraApplication
from cura.Machines.ContainerTree import ContainerTree


class MaterialTypesModel(ListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        QQmlEngine.setObjectOwnership(self, QQmlEngine.ObjectOwnership.CppOwnership)
        self.addRoleName(Qt.ItemDataRole.UserRole + 1, "name")
        self.addRoleName(Qt.ItemDataRole.UserRole + 2, "brand")
        self.addRoleName(Qt.ItemDataRole.UserRole + 3, "colors")


class AllMaterialBrandsModel(BaseMaterialsModel):
    """Drop-in replacement for MaterialBrandsModel that bypasses the diameter
    filter baked into the frozen BaseMaterialsModel._update().

    Registered as Cura.MaterialBrandsModel so all QML that uses that type
    automatically gets this unfiltered version instead.
    """

    extruderPositionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        QQmlEngine.setObjectOwnership(self, QQmlEngine.ObjectOwnership.CppOwnership)
        self.addRoleName(Qt.ItemDataRole.UserRole + 1, "name")
        self.addRoleName(Qt.ItemDataRole.UserRole + 2, "material_types")
        self._update()

    def _update(self):
        if not self._canUpdate():
            return

        # Replicate the favorites setup from BaseMaterialsModel._update() so
        # _createMaterialItem() can mark favourites correctly.
        self._favorite_ids = set(
            cura.CuraApplication.CuraApplication.getInstance()
            .getPreferences().getValue("cura/favorite_materials").split(";")
        )

        # Fetch ALL materials for the current nozzle variant — no diameter filter.
        # VariantNode.materials is explicitly documented as containing every
        # material regardless of diameter; filtering is meant to happen in models.
        global_stack = cura.CuraApplication.CuraApplication.getInstance().getGlobalContainerStack()
        if not global_stack or not global_stack.hasMaterials:
            return
        if self._extruder_stack is None:
            return

        nozzle_name = self._extruder_stack.variant.getName()
        machine_node = ContainerTree.getInstance().machines[global_stack.definition.getId()]
        if nozzle_name not in machine_node.variants:
            Logger.log("w", "AllMaterialBrandsModel: variant %s not found", nozzle_name)
            self._available_materials = {}
            return

        self._available_materials = dict(machine_node.variants[nozzle_name].materials)

        # Build brand -> material_type -> colors tree (same logic as the original
        # MaterialBrandsModel._update(), generic brand excluded as before).
        brand_item_list = []
        brand_group_dict = {}

        for root_material_id, container_node in self._available_materials.items():
            if bool(container_node.getMetaDataEntry("removed", False)):
                continue
            if not bool(container_node.getMetaDataEntry("visible", True)):
                continue
            brand = container_node.getMetaDataEntry("brand", "")
            if brand.lower() != "printess":
                continue
            if brand not in brand_group_dict:
                brand_group_dict[brand] = {}
            material_type = container_node.getMetaDataEntry("material", "")
            if material_type not in brand_group_dict[brand]:
                brand_group_dict[brand][material_type] = []
            item = self._createMaterialItem(root_material_id, container_node)
            if item:
                brand_group_dict[brand][material_type].append(item)

        for brand, material_dict in brand_group_dict.items():
            material_type_item_list = []
            brand_item = {
                "name": brand,
                "material_types": MaterialTypesModel()
            }
            for material_type, material_list in material_dict.items():
                material_type_item = {
                    "name": material_type,
                    "brand": brand,
                    "colors": BaseMaterialsModel()
                }
                material_list = sorted(material_list, key=lambda x: x["name"].upper())
                material_type_item["colors"].setItems(material_list)
                material_type_item_list.append(material_type_item)

            material_type_item_list = sorted(material_type_item_list, key=lambda x: x["name"].upper())
            brand_item["material_types"].setItems(material_type_item_list)
            brand_item_list.append(brand_item)

        brand_item_list = sorted(brand_item_list, key=lambda x: x["name"].upper())
        self.setItems(brand_item_list)
