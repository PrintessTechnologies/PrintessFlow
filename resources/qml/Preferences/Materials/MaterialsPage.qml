// Copyright (c) 2022 Ultimaker B.V.
// Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.7
import QtQuick.Controls 2.15
import QtQuick.Dialogs

import UM 1.5 as UM
import Cura 1.5 as Cura

UM.ManagementPage
{
    id: base
    Item { enabled: false; UM.I18nCatalog { id: catalog; name: "cura"} }
    // Keep PreferencesDialog happy
    property var resetEnabled: false
    property var currentItem: null

    property var materialManagementModel: CuraApplication.getMaterialManagementModel()

    property var hasCurrentItem: base.currentItem != null
    property var isCurrentItemActivated:
    {
        if (!hasCurrentItem)
        {
            return false
        }
        const extruder_position = Cura.ExtruderManager.activeExtruderIndex
        const root_material_id = Cura.MachineManager.currentRootMaterialId[extruder_position]
        return base.currentItem.root_material_id == root_material_id
    }
    property string newRootMaterialIdToSwitchTo: ""
    property bool toActivateNewMaterial: false
    property bool _pendingPrintessRename: false
    property bool _pendingDiameterDialog: false
    property bool _pendingRandomColor: false

    property var extruder_position: Cura.ExtruderManager.activeExtruderIndex
    property var active_root_material_id: Cura.MachineManager.currentRootMaterialId[extruder_position]

    function randomMaterialColor()
    {
        var h = Math.random()
        var s = 0.75, l = 0.50
        var c = (1 - Math.abs(2 * l - 1)) * s
        var x = c * (1 - Math.abs((h * 6) % 2 - 1))
        var m = l - c / 2
        var r, g, b
        var h6 = h * 6
        if      (h6 < 1) { r = c; g = x; b = 0 }
        else if (h6 < 2) { r = x; g = c; b = 0 }
        else if (h6 < 3) { r = 0; g = c; b = x }
        else if (h6 < 4) { r = 0; g = x; b = c }
        else if (h6 < 5) { r = x; g = 0; b = c }
        else             { r = c; g = 0; b = x }
        var toHex = function(v) { var s = Math.round((v + m) * 255).toString(16); return s.length < 2 ? "0" + s : s }
        return "#" + toHex(r) + toHex(g) + toHex(b)
    }

    function resetExpandedActiveMaterial()
    {
        materialListView.expandActiveMaterial(active_root_material_id)
    }

    function setExpandedActiveMaterial(root_material_id)
    {
        materialListView.expandActiveMaterial(root_material_id)
    }

    // When loaded, try to select the active material in the tree
    Component.onCompleted:
    {
        resetExpandedActiveMaterial()
        base.newRootMaterialIdToSwitchTo = active_root_material_id
    }

    // Every time the selected item has changed, notify to the details panel
    onCurrentItemChanged:
    {
        forceActiveFocus()
        if(materialDetailsPanel.currentItem != currentItem)
        {
            materialDetailsPanel.currentItem = currentItem
            // CURA-6679 If the current item is gone after the model update, reset the current item to the active material.
            if (currentItem == null)
            {
                resetExpandedActiveMaterial()
            }
        }
        if (_pendingPrintessRename && currentItem != null)
        {
            _pendingPrintessRename = false
            base.materialManagementModel.setMaterialName(currentItem.container_node, "New Syringe")
            Cura.ContainerManager.unlinkMaterial(currentItem.container_node)
        }
        if (_pendingRandomColor && currentItem != null)
        {
            _pendingRandomColor = false
            Cura.ContainerManager.setContainerMetaDataEntry(currentItem.container_node, "color_code", randomMaterialColor())
        }
        if (_pendingDiameterDialog && currentItem != null)
        {
            _pendingDiameterDialog = false
            var nodeToSet = currentItem.container_node
            var idToActivate = currentItem.root_material_id
            Qt.callLater(function() {
                diameterInputDialog.targetNode = nodeToSet
                diameterInputDialog.pendingMaterialId = idToActivate
                diameterInputDialog.open()
            })
        }
    }

    title: catalog.i18nc("@title:tab", "Syringes")
    detailsPlaneCaption: currentItem ? currentItem.name: ""
    scrollviewCaption: catalog.i18nc("@label", "Syringes compatible with active printer:") + `<br /><b>${Cura.MachineManager.activeMachine.name}</b>`

    buttons: [
        Cura.SecondaryButton
        {
            id: createMenuButton
            text: catalog.i18nc("@action:button", "Create new")
            enabled: Cura.MachineManager.activeMachine.hasMaterials
            onClicked:
            {
                forceActiveFocus()
                var printessNode = null
                for (var i = 0; i < printessBrandsModel.count; i++)
                {
                    var brand = printessBrandsModel.getItem(i)
                    if (brand.name === "Printess")
                    {
                        var types = brand.material_types
                        if (types.count > 0)
                        {
                            var colors = types.getItem(0).colors
                            if (colors.count > 0)
                            {
                                printessNode = colors.getItem(0).container_node
                            }
                        }
                        break
                    }
                }
                if (printessNode !== null)
                {
                    base._pendingPrintessRename = true
                    base._pendingRandomColor = true
                    base._pendingDiameterDialog = true
                    base.newRootMaterialIdToSwitchTo = base.materialManagementModel.duplicateMaterial(printessNode)
                    base.toActivateNewMaterial = false
                }
                else
                {
                    base._pendingRandomColor = true
                    base._pendingDiameterDialog = true
                    base.newRootMaterialIdToSwitchTo = base.materialManagementModel.createMaterial()
                    base.toActivateNewMaterial = false
                }
            }
        },
        Cura.SecondaryButton
        {
            id: importMenuButton
            text: catalog.i18nc("@action:button", "Import")
            onClicked:
            {
                forceActiveFocus();
                importMaterialDialog.open();
            }
            enabled: Cura.MachineManager.activeMachine.hasMaterials
        },
        Cura.SecondaryButton
        {
            id: syncMaterialsButton
            text: catalog.i18nc("@action:button", "Sync with Printers")
            onClicked:
            {
                forceActiveFocus();
                base.materialManagementModel.openSyncAllWindow();
            }
            visible: Cura.MachineManager.activeMachine.supportsMaterialExport
        }
    ]

    onHamburgeButtonClicked: {
        const hamburerButtonHeight = hamburger_button.height;
        menu.popup(hamburger_button, -menu.width + hamburger_button.width / 2, hamburger_button.height);
        // for some reason the height of the hamburger changes when opening the popup
        // reset height to initial heigt
        hamburger_button.height = hamburerButtonHeight;
    }
    listContent: ScrollView
    {
        id: materialScrollView
        anchors.fill: parent
        anchors.margins: parent.border.width
        width: (parent.width * 0.4) | 0

        clip: true
        ScrollBar.vertical: UM.ScrollBar
        {
            id: materialScrollBar
            parent: materialScrollView.parent
            anchors
            {
                top: parent.top
                right: parent.right
                bottom: parent.bottom
            }
        }
        contentHeight: materialListView.height //For some reason, this is not determined automatically with this ScrollView. Very weird!

        MaterialsList
        {
            id: materialListView
            width: materialScrollView.width - materialScrollBar.width
        }
    }

    MaterialsDetailsPanel
    {
        id: materialDetailsPanel
        anchors.fill: parent
    }

    Item
    {
        Cura.AllMaterialBrandsModel
        {
            id: printessBrandsModel
            extruderPosition: Cura.ExtruderManager.activeExtruderIndex
        }

        Cura.Menu
        {
            id: menu
            Cura.MenuItem
            {
                id: activateMenuButton
                text: catalog.i18nc("@action:button", "Activate")
                onClicked:
                {
                    forceActiveFocus()

                    // Set the current material as the one to be activated (needed to force the UI update)
                    base.newRootMaterialIdToSwitchTo = base.currentItem.root_material_id
                    const extruder_position = Cura.ExtruderManager.activeExtruderIndex
                    Cura.MachineManager.setMaterial(extruder_position, base.currentItem.container_node)
                }
            }
            Cura.MenuItem
            {
                id: duplicateMenuButton
                text: catalog.i18nc("@action:button", "Duplicate");
                enabled: base.hasCurrentItem
                onClicked:
                {
                    forceActiveFocus();
                    base.newRootMaterialIdToSwitchTo = base.materialManagementModel.duplicateMaterial(base.currentItem.container_node);
                    base.toActivateNewMaterial = true;
                }
            }
            Cura.MenuItem
            {
                id: removeMenuButton
                text: catalog.i18nc("@action:button", "Remove")
                enabled: base.hasCurrentItem && !base.currentItem.is_read_only && !base.isCurrentItemActivated && base.materialManagementModel.canMaterialBeRemoved(base.currentItem.container_node)

                onClicked:
                {
                    forceActiveFocus();
                    confirmRemoveMaterialDialog.open();
                }
            }
            Cura.MenuItem
            {
                id: exportMenuButton
                text: catalog.i18nc("@action:button", "Export")
                onClicked:
                {
                    forceActiveFocus();
                    exportMaterialDialog.open();
                }
                enabled: base.hasCurrentItem
            }
        }

        // Dialogs
        Dialog
        {
            id: diameterInputDialog
            title: catalog.i18nc("@title:window", "Configure New Syringe")
            modal: true
            anchors.centerIn: Overlay.overlay
            padding: UM.Theme.getSize("default_margin").width
            standardButtons: Dialog.NoButton

            property var targetNode: null
            property string pendingMaterialId: ""

            onClosed:
            {
                if (pendingMaterialId !== "")
                {
                    Cura.MachineManager.setMaterialById(Cura.ExtruderManager.activeExtruderIndex, pendingMaterialId)
                    pendingMaterialId = ""
                }
            }

            background: Rectangle { color: UM.Theme.getColor("detail_background") }

            header: UM.Label
            {
                text: diameterInputDialog.title
                font: UM.Theme.getFont("medium_bold")
                topPadding: diameterInputDialog.padding
                leftPadding: diameterInputDialog.padding
                rightPadding: diameterInputDialog.padding
            }

            contentItem: Column
            {
                spacing: UM.Theme.getSize("default_margin").height
                // Scaled: bare numbers do not follow the display scaling that
                // the fonts inside them do (see Theme.py).
                width: Math.round(320 * screenScaleFactor)

                UM.Label
                {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: catalog.i18nc("@label", "Enter the details for your new syringe. Both fields are optional — you can edit them later in the Syringes panel.")
                }

                // ── Syringe Size ─────────────────────────────────────────────

                UM.Label
                {
                    text: catalog.i18nc("@label", "Syringe Size")
                    font: UM.Theme.getFont("default_bold")
                }

                UM.Label
                {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: UM.Theme.getColor("text_medium")
                    text: catalog.i18nc("@label", "Names the syringe \"#mL Syringe\" where # is the number you enter.")
                    font: UM.Theme.getFont("default")
                }

                Row
                {
                    spacing: UM.Theme.getSize("narrow_margin").width

                    TextField
                    {
                        id: syringeField
                        width: Math.round(120 * screenScaleFactor)
                        placeholderText: "e.g. 3"
                        selectByMouse: true
                        validator: DoubleValidator
                        {
                            bottom: 0.1
                            top: 9999
                            decimals: 2
                            notation: DoubleValidator.StandardNotation
                        }
                        Keys.onReturnPressed: diameterField.forceActiveFocus()
                        Keys.onEnterPressed: diameterField.forceActiveFocus()
                    }

                    UM.Label
                    {
                        text: "mL"
                        anchors.verticalCenter: syringeField.verticalCenter
                    }
                }

                // ── Inner Diameter ────────────────────────────────────────────

                UM.Label
                {
                    text: catalog.i18nc("@label", "Inner Barrel Diameter")
                    font: UM.Theme.getFont("default_bold")
                }

                UM.Label
                {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: UM.Theme.getColor("text_medium")
                    text: catalog.i18nc("@label", "Sets the material's diameter field, which controls extrusion volume calculations.")
                    font: UM.Theme.getFont("default")
                }

                Row
                {
                    spacing: UM.Theme.getSize("narrow_margin").width

                    TextField
                    {
                        id: diameterField
                        width: Math.round(120 * screenScaleFactor)
                        placeholderText: "e.g. 4.76"
                        selectByMouse: true
                        validator: DoubleValidator
                        {
                            bottom: 0.01
                            top: 100
                            decimals: 4
                            notation: DoubleValidator.StandardNotation
                        }
                        Keys.onReturnPressed: diameterInputDialog.applyAndClose()
                        Keys.onEnterPressed: diameterInputDialog.applyAndClose()
                    }

                    UM.Label
                    {
                        text: "mm"
                        anchors.verticalCenter: diameterField.verticalCenter
                    }
                }
            }

            footer: Row
            {
                spacing: UM.Theme.getSize("default_margin").width
                padding: diameterInputDialog.padding
                layoutDirection: Qt.RightToLeft

                Cura.PrimaryButton
                {
                    text: catalog.i18nc("@action:button", "Apply")
                    onClicked: diameterInputDialog.applyAndClose()
                }

                Cura.SecondaryButton
                {
                    text: catalog.i18nc("@action:button", "Skip")
                    onClicked: diameterInputDialog.close()
                }
            }

            function applyAndClose()
            {
                if (targetNode !== null)
                {
                    if (syringeField.acceptableInput && syringeField.text !== "")
                    {
                        var sizeName = syringeField.text.replace(",", ".") + "mL Syringe"
                        base.materialManagementModel.setMaterialName(targetNode, sizeName)
                    }
                    if (diameterField.acceptableInput && diameterField.text !== "")
                    {
                        var diamVal = diameterField.text.replace(",", ".")
                        Cura.ContainerManager.setContainerMetaDataEntry(targetNode, "properties/diameter", diamVal)
                    }
                }
                close()
            }

            onOpened:
            {
                syringeField.text = ""
                diameterField.text = ""
                syringeField.forceActiveFocus()
            }
        }

        Cura.MessageDialog
        {
            id: confirmRemoveMaterialDialog
            title: catalog.i18nc("@title:window", "Confirm Remove")
            property string materialName: base.currentItem !== null ? base.currentItem.name : ""

            text: catalog.i18nc("@label (%1 is object name)", "Are you sure you wish to remove %1? This cannot be undone!").arg(materialName)
            standardButtons: Dialog.Yes | Dialog.No
            onAccepted:
            {
                // Set the active material as the fallback. It will be selected when the current material is deleted
                base.newRootMaterialIdToSwitchTo = base.active_root_material_id
                base.materialManagementModel.removeMaterial(base.currentItem.container_node);
            }
        }

        FileDialog
        {
            id: importMaterialDialog
            title: catalog.i18nc("@title:window", "Import Syringe")
            fileMode: FileDialog.OpenFile
            nameFilters: Cura.ContainerManager.getContainerNameFilters("material")
            currentFolder: CuraApplication.getDefaultPath("dialog_material_path")
            onAccepted:
            {
                const result = Cura.ContainerManager.importMaterialContainer(selectedFile);

                const messageDialog = Qt.createQmlObject("import Cura 1.5 as Cura; Cura.MessageDialog { onClosed: destroy() }", base);
                messageDialog.standardButtons = Dialog.Ok;
                messageDialog.title = catalog.i18nc("@title:window", "Import Syringe");
                switch (result.status)
                {
                    case "success":
                        messageDialog.text = catalog.i18nc("@info:status Don't translate the XML tag <filename>!", "Successfully imported syringe <filename>%1</filename>").arg(selectedFile);
                        break;
                    default:
                        messageDialog.text = catalog.i18nc("@info:status Don't translate the XML tags <filename> or <message>!", "Could not import syringe <filename>%1</filename>: <message>%2</message>").arg(selectedFile).arg(result.message);
                        break;
                }
                messageDialog.open();
                CuraApplication.setDefaultPath("dialog_material_path", currentFolder);
            }
        }

        FileDialog
        {
            id: exportMaterialDialog
            title: catalog.i18nc("@title:window", "Export Syringe")
            fileMode: FileDialog.SaveFile
            nameFilters: Cura.ContainerManager.getContainerNameFilters("material")
            currentFolder: CuraApplication.getDefaultPath("dialog_material_path")
            onAccepted:
            {
                const nameFilterString = selectedNameFilter.index >= 0 ? nameFilters[selectedNameFilter.index] : nameFilters[0];

                const result = Cura.ContainerManager.exportContainer(base.currentItem.root_material_id, nameFilterString, selectedFile);

                const messageDialog = Qt.createQmlObject("import Cura 1.5 as Cura; Cura.MessageDialog { onClosed: destroy() }", base);
                messageDialog.title = catalog.i18nc("@title:window", "Export Syringe");
                messageDialog.standardButtons = Dialog.Ok;
                switch (result.status)
                {
                    case "error":
                        messageDialog.text = catalog.i18nc("@info:status Don't translate the XML tags <filename> and <message>!", "Failed to export syringe to <filename>%1</filename>: <message>%2</message>").arg(selectedFile).arg(result.message);
                        break;
                    case "success":
                        messageDialog.text = catalog.i18nc("@info:status Don't translate the XML tag <filename>!", "Successfully exported syringe to <filename>%1</filename>").arg(result.path);
                        break;
                }
                messageDialog.open();

                CuraApplication.setDefaultPath("dialog_material_path", currentFolder);
            }
        }
    }
}
