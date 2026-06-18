//Copyright (c) 2022 Ultimaker B.V.
//Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.7
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.3
import QtQuick.Dialogs

import UM 1.5 as UM
import Cura 1.6 as Cura


UM.ManagementPage
{
    id: base
    Item { enabled: false; UM.I18nCatalog { id: catalog; name: "cura"} }

    property var extrudersModel: CuraApplication.getExtrudersModel()
    property var qualityManagementModel: CuraApplication.getQualityManagementModel()
    property bool hasCurrentItem: base.currentItem != null

    property var currentItem: objectList.currentIndex == -1 ? null : base.qualityManagementModel.getItem(objectList.currentIndex)

    property string currentItemName: hasCurrentItem ? base.currentItem.name : ""
    property string currentItemDisplayName: hasCurrentItem ? base.qualityManagementModel.getQualityItemDisplayName(base.currentItem) : ""

    property bool isCurrentItemActivated:
    {
        if (!base.currentItem)
        {
            return false;
        }
        if (base.currentItem.is_read_only)
        {
            return (base.currentItem.name == Cura.MachineManager.activeQualityOrQualityChangesName) && (base.currentItem.intent_category == Cura.MachineManager.activeIntentCategory);
        }
        else
        {
            return base.currentItem.name == Cura.MachineManager.activeQualityOrQualityChangesName;
        }
    }

    property bool canCreateProfile:  Cura.MachineManager.hasUserSettings

    readonly property var tipColorMap: ({
        "Nordson Olive 1.54mm ID": "#808000",
        "Nordson Amber 1.36mm ID": "#FFBF00",
        "Nordson Green 0.84mm ID": "#00A550",
        "Nordson Pink 0.61mm ID": "#FF69B4",
        "Nordson Purple 0.51mm ID": "#800080",
        "Nordson Blue 0.41mm ID": "#0057A8",
        "Nordson Orange 0.33mm ID": "#FF8C00",
        "Nordson Red 0.25mm ID": "#CC0000",
        "Nordson Clear 0.20mm ID": "#FFFFFF",
        "Nordson Lavender 0.15mm ID": "#B57EDC",
        "Nordson Yellow 0.10mm ID": "#FFD700"
    })

    function getCustomTipColor(name)
    {
        var raw = UM.Preferences.getValue("printess/tip_colors")
        if (!raw) return ""
        try { return JSON.parse(raw)[name] || "" } catch(e) { return "" }
    }

    signal createProfile() // Click create profile from ... in Profile context menu

    property string newQualityNameToSelect: ""
    property bool toActivateNewQuality: false

    onCreateProfile:
    {
        createQualityDialog.object = Cura.ContainerManager.makeUniqueName(Cura.MachineManager.activeQualityOrQualityChangesName);
        createQualityDialog.open();
        createQualityDialog.selectText();
    }

    title: catalog.i18nc("@title:tab", "Dispense Tips")
    detailsPlaneCaption: base.currentItemDisplayName
    scrollviewCaption: catalog.i18nc("@label", "Dispense Tips compatible with active printer:") + "<br><b>" + Cura.MachineManager.activeMachine.name + "</b>"

    hamburgerButtonVisible: hasCurrentItem
    onHamburgeButtonClicked: (hamburger_button) => {
        const hamburerButtonHeight = hamburger_button.height;
        menu.popup(hamburger_button, -menu.width + hamburger_button.width / 2, hamburger_button.height);

        // for some reason the height of the hamburger changes when opening the popup
        // reset height to initial heigt
        hamburger_button.height = hamburerButtonHeight;
    }

    isActiveModelFunction: function(model, id) {
        if (model.is_read_only)
        {
            return (model.name == Cura.MachineManager.activeQualityOrQualityChangesName) && (model.intent_category == Cura.MachineManager.activeIntentCategory);
        }
        else
        {
            return model.name == Cura.MachineManager.activeQualityOrQualityChangesName;
        }
    }

    sectionRole: "section_name"

    model: qualityManagementModel

    // Hide section headers that are not "Syringe Profile Options" (e.g. "Balanced" from built-in quality groups)
    section.delegate: Rectangle
    {
        width: ListView.view ? ListView.view.width : 0
        height: section === catalog.i18nc("@label", "Syringe Profile Options") ? (sectionLabel.height + UM.Theme.getSize("narrow_margin").height) : 0
        clip: true
        color: UM.Theme.getColor("background_1")

        UM.Label
        {
            id: sectionLabel
            visible: parent.height > 0
            anchors.left: parent.left
            anchors.leftMargin: UM.Theme.getSize("default_lining").width
            anchors.verticalCenter: parent.verticalCenter
            text: catalog.i18nc("@label", "Dispense Tip Options")
            font: UM.Theme.getFont("default_bold")
            color: UM.Theme.getColor("text_default")
        }
    }

    // Hide read-only items (built-in quality profiles such as Draft, Fine, etc.)
    delegate: Rectangle
    {
        width: ListView.view ? ListView.view.width - UM.Theme.getSize("scrollbar").width : 0
        height: model.is_read_only ? 0 : childrenRect.height
        clip: true
        color: ListView.isCurrentItem ? UM.Theme.getColor("text_selection") : UM.Theme.getColor("main_background")

        UM.Label
        {
            id: nameLabel
            visible: !model.is_read_only
            anchors.left: parent.left
            anchors.leftMargin: UM.Theme.getSize("default_margin").width
            anchors.right: profileOval.left
            anchors.rightMargin: UM.Theme.getSize("narrow_margin").width
            text: model.name
            elide: Text.ElideRight
            font: base.isActiveModelFunction(model, base.activeId) ? UM.Theme.getFont("default_italic") : UM.Theme.getFont("default")
            wrapMode: Text.NoWrap
        }

        Rectangle
        {
            id: profileOval
            property string resolvedColor:
            {
                var c = base.tipColorMap[model.name]
                if (c !== undefined) return c
                return base.getCustomTipColor(model.name)
            }
            visible: !model.is_read_only && resolvedColor !== ""
            width: visible ? Math.round(height * 1.6) : 0
            height: Math.round(nameLabel.contentHeight * 0.85)
            radius: height / 2
            color: resolvedColor !== "" ? resolvedColor : "transparent"
            border.width: resolvedColor === "#FFFFFF" ? 1 : 0
            border.color: "#888888"
            anchors.verticalCenter: nameLabel.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: UM.Theme.getSize("default_margin").width
        }

        MouseArea
        {
            anchors.fill: parent
            enabled: !model.is_read_only
            onClicked:
            {
                if (!parent.ListView.isCurrentItem)
                {
                    parent.ListView.view.currentIndex = index
                    base.itemActivated()
                }
            }
        }
    }
    buttons: [
        Cura.SecondaryButton
        {
            text: catalog.i18nc("@action:button", "Import")
            onClicked:importDialog.open()
        },
        Cura.SecondaryButton
        {
            id: createMenuButton
            text: catalog.i18nc("@action:button", "Create new")

            enabled: !Cura.MachineErrorChecker.hasError
            visible: base.canCreateProfile
            tooltip: catalog.i18nc("@action:tooltip", "Create new dispense tip from current settings/overrides")
            onClicked:
            {
                createQualityDialog.object = Cura.ContainerManager.makeUniqueName("<new name>")
                createQualityDialog.open()
                createQualityDialog.selectText()
            }
        }
    ]

    Column
    {
        id: detailsPanelHeaderColumn
        anchors
        {
            left: parent.left
            right: parent.right
            top: parent.top
        }

        spacing: UM.Theme.getSize("default_margin").height
        visible: base.currentItem != null

        UM.Label
        {
            anchors.left: parent.left
            anchors.right: parent.right
            text: catalog.i18nc("@action:label", "Some settings from current dispense tip were overwritten.")
            visible: currentSettingsActions.visible
        }

        Flow
        {
            id: currentSettingsActions
            width: parent.width

            visible: false

            spacing: UM.Theme.getSize("default_margin").width

            Cura.SecondaryButton
            {
                text: catalog.i18nc("@action:button", "Update dispense tip.")
                enabled: Cura.MachineManager.hasUserSettings && objectList.currentIndex && !objectList.currentIndex.is_read_only
                onClicked: Cura.ContainerManager.updateQualityChanges()
                tooltip: catalog.i18nc("@action:tooltip", "Update dispense tip with current settings/overrides")
            }

            Cura.SecondaryButton
            {
                text: catalog.i18nc("@action:button", "Discard current changes")
                enabled: Cura.MachineManager.hasUserSettings
                onClicked: Cura.ContainerManager.clearUserContainers()
            }
        }

        UM.Label
        {
            id: defaultsMessage
            visible: false
            text: catalog.i18nc("@action:label", "This dispense tip uses the defaults specified by the printer, so it has no settings/overrides in the list below.")
            width: parent.width
        }
        UM.Label
        {
            id: noCurrentSettingsMessage
            visible: base.isCurrentItemActivated && !Cura.MachineManager.hasUserSettings
            text: catalog.i18nc("@action:label", "Your current settings match the selected dispense tip.")
            width: parent.width
        }

        UM.TabRow
        {
            id: profileExtruderTabs
            // One extra tab for the global settings.
            UM.TabRowButton
            {
                text: catalog.i18nc("@title:tab", "Global Settings")
            }

            Repeater
            {
                model: base.extrudersModel

                UM.TabRowButton
                {
                    text: model.name
                }
            }
        }
    }

    Rectangle
    {
        color: UM.Theme.getColor("main_background")
        anchors
        {
            top: detailsPanelHeaderColumn.bottom
            topMargin: -UM.Theme.getSize("default_lining").width
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        border.width: UM.Theme.getSize("default_lining").width
        border.color: UM.Theme.getColor("thick_lining")
        visible: base.hasCurrentItem
    }

    Cura.ProfileOverview
    {
        anchors
        {
            top: detailsPanelHeaderColumn.bottom
            margins: UM.Theme.getSize("default_margin").height
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }

        visible: detailsPanelHeaderColumn.visible
        qualityItem: base.currentItem
        extruderPosition: profileExtruderTabs.currentIndex - 1
    }

    Item
    {
        id: content_item
        anchors.fill: parent
        // This connection makes sure that we will switch to the correct quality after the model gets updated
        Connections
        {
            target: base.qualityManagementModel
            function onItemsChanged()
            {
                var toSelectItemName = base.currentItem == null ? "" : base.currentItem.name;
                if (newQualityNameToSelect != "")
                {
                    toSelectItemName = newQualityNameToSelect;
                }

                var newIdx = -1;  // Default to nothing if nothing can be found
                if (toSelectItemName != "")
                {
                    // Select the required quality name if given
                    for (var idx = 0; idx < base.qualityManagementModel.count; ++idx)
                    {
                        var item = base.qualityManagementModel.getItem(idx);
                        if (item && item.name == toSelectItemName)
                        {
                            // Switch to the newly created profile if needed
                            newIdx = idx;
                            if (base.toActivateNewQuality)
                            {
                                // Activate this custom quality if required
                                if(item.quality_changes_group)
                                {
                                    Cura.MachineManager.setQualityChangesGroup(item.quality_changes_group);
                                }
                            }
                            break;
                        }
                    }
                }
                objectList.currentIndex = newIdx;

                // Reset states
                base.newQualityNameToSelect = "";
                base.toActivateNewQuality = false;
            }
        }
        Cura.MessageDialog
        {
            id: messageDialog
            standardButtons: Dialog.Ok
        }

        // Dialog to request a name when creating a new profile
        Cura.RenameDialog
        {
            id: createQualityDialog
            title: catalog.i18nc("@title:window", "Create Dispense Tip")
            object: "<new name>"
            explanation: catalog.i18nc("@info", "Please provide a name for this dispense tip.")
            onAccepted:
            {
                base.newQualityNameToSelect = newName;  // We want to switch to the new profile once it's created
                base.toActivateNewQuality = true;
                base.qualityManagementModel.createQualityChanges(newName);
            }
        }

        Cura.Menu
        {
            id: menu
            Cura.MenuItem
            {
                text: catalog.i18nc("@action:button", "Activate")

                enabled: !isCurrentItemActivated && base.currentItem
                onTriggered:
                {
                    // Auto-save current profile's live edits before switching, then clear
                    // userChanges so the incoming profile loads with its own clean settings.
                    Cura.ContainerManager.updateQualityChanges()
                    Cura.ContainerManager.clearUserContainers()

                    if(base.currentItem.is_read_only)
                    {
                        Cura.IntentManager.selectIntent(base.currentItem.intent_category, base.currentItem.quality_type)
                    }
                    else
                    {
                        Cura.MachineManager.setQualityChangesGroup(base.currentItem.quality_changes_group)
                    }
                }
            }
            Cura.MenuItem
            {
                text: catalog.i18nc("@action:button", "Duplicate")
                enabled: base.hasCurrentItem
                onTriggered:
                {
                    forceActiveFocus()
                    duplicateQualityDialog.open()
                }
            }
            Cura.MenuItem
            {
                text: catalog.i18nc("@action:button", "Remove")
                enabled: base.hasCurrentItem && !base.currentItem.is_read_only && !base.isCurrentItemActivated
                onTriggered:
                {
                    forceActiveFocus()
                    confirmRemoveQualityDialog.open()
                }
            }
            Cura.MenuItem
            {
                text: catalog.i18nc("@action:button", "Rename")
                enabled: base.hasCurrentItem && !base.currentItem.is_read_only
                onTriggered:
                {
                    renameQualityDialog.object = base.currentItem.name
                    renameQualityDialog.open()
                    renameQualityDialog.selectText()
                }
            }
            Cura.MenuItem
            {
                text: catalog.i18nc("@action:button", "Export")
                enabled: base.hasCurrentItem && !base.currentItem.is_read_only
                onTriggered: exportDialog.open()
            }
        }

        // Dialog for exporting a quality profile
        FileDialog
        {
            id: exportDialog
            title: catalog.i18nc("@title:window", "Export Profile")
            fileMode: FileDialog.SaveFile
            nameFilters: base.qualityManagementModel.getFileNameFilters("profile_writer")
            currentFolder: CuraApplication.getDefaultPath("dialog_profile_path")
            onAccepted:
            {

                // If nameFilters contains only 1 item, the index of selectedNameFilter will always be -1
                // This fetches the nameFilter at index selectedNameFilter.index if it is positive
                const nameFilterString = selectedNameFilter.index >= 0 ? nameFilters[selectedNameFilter.index] : nameFilters[0];

                var result = Cura.ContainerManager.exportQualityChangesGroup(base.currentItem.quality_changes_group,
                                                                             selectedFile, nameFilterString);

                if (result && result.status == "error")
                {
                    messageDialog.title = catalog.i18nc("@title:window", "Export Profile")
                    messageDialog.text = result.message;
                    messageDialog.open();
                }

                // else pop-up Message thing from python code
                CuraApplication.setDefaultPath("dialog_profile_path", currentFolder);
            }
        }

        // Dialog to request a name when duplicating a new profile
        Cura.RenameDialog
        {
            id: duplicateQualityDialog
            title: catalog.i18nc("@title:window", "Duplicate Dispense Tip")
            object: "<new name>"
            onAccepted: base.qualityManagementModel.duplicateQualityChanges(newName, base.currentItem)
        }

        // Confirmation dialog for removing a profile
        Cura.MessageDialog
        {
            id: confirmRemoveQualityDialog

            title: catalog.i18nc("@title:window", "Confirm Remove")
            text: catalog.i18nc("@label (%1 is object name)", "Are you sure you wish to remove %1? This cannot be undone!").arg(base.currentItemName)
            standardButtons: Dialog.Yes | Dialog.No
            modal: true

            onAccepted:
            {
                base.qualityManagementModel.removeQualityChangesGroup(base.currentItem.quality_changes_group);
                // reset current item to the first if available
                qualityListView.currentIndex = -1;  // Reset selection.
            }
        }

        // Dialog to rename a quality profile
        Cura.RenameDialog
        {
            id: renameQualityDialog
            title: catalog.i18nc("@title:window", "Rename Dispense Tip")
            object: "<new name>"
            onAccepted:
            {
                var actualNewName = base.qualityManagementModel.renameQualityChangesGroup(base.currentItem.quality_changes_group, newName);
                base.newQualityNameToSelect = actualNewName;  // Select the new name after the model gets updated
            }
        }

        // Dialog for importing a quality profile
        FileDialog
        {
            id: importDialog
            title: catalog.i18nc("@title:window", "Import Profile")
            fileMode: FileDialog.OpenFile
            nameFilters: base.qualityManagementModel.getFileNameFilters("profile_reader")
            currentFolder: CuraApplication.getDefaultPath("dialog_profile_path")
            onAccepted:
            {
                var result = Cura.ContainerManager.importProfile(selectedFile);
                messageDialog.title = catalog.i18nc("@title:window", "Import Profile")
                messageDialog.text = result.message;
                messageDialog.open();
                CuraApplication.setDefaultPath("dialog_profile_path", folder);
            }
        }
    }
}
