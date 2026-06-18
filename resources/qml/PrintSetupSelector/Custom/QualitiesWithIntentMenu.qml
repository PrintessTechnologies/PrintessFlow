// Copyright (c) 2022 Ultimaker B.V.
// Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.10
import QtQuick.Controls 2.3

import UM 1.5 as UM
import Cura 1.6 as Cura

Popup
{
    id: popup
    implicitWidth: 400
    property var dataModel: Cura.IntentCategoryModel {}

    property int defaultMargin: UM.Theme.getSize("default_margin").width
    property color backgroundColor: UM.Theme.getColor("main_background")
    property color borderColor: UM.Theme.getColor("lining")

    // ── State ─────────────────────────────────────────────────────────────────
    property bool showCreateForm: false
    property string createFormColor: "#E53935"
    property real createFormLineWidth: 0.0

    // Bumped whenever custom colors are written so delegate bindings re-evaluate
    property int colorVersion: 0

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

    readonly property var colorPalette: [
        "#E53935", "#FB8C00", "#FDD835", "#7CB342", "#1E88E5", "#8E24AA",
        "#D81B60", "#00897B", "#039BE5", "#5E35B1", "#43A047", "#F4511E",
        "#6D4C41", "#546E7A", "#00ACC1", "#3949AB", "#C0CA33", "#757575"
    ]

    // ── Color helpers (UM.Preferences JSON — no Python call needed) ──────────
    function getCustomTipColor(name)
    {
        var raw = UM.Preferences.getValue("printess/tip_colors")
        if (!raw) return ""
        try { return JSON.parse(raw)[name] || "" } catch(e) { return "" }
    }

    function saveCustomTipColor(name, color)
    {
        UM.Preferences.addPreference("printess/tip_colors", "{}")
        var raw = UM.Preferences.getValue("printess/tip_colors") || "{}"
        try
        {
            var colors = JSON.parse(raw)
            colors[name] = color
            UM.Preferences.setValue("printess/tip_colors", JSON.stringify(colors))
        } catch(e) {}
    }

    // ── Core logic ────────────────────────────────────────────────────────────
    function doCreate()
    {
        var name = tipNameField.text.trim()
        if (name === "") return

        // Close the popup first — profile creation is async and must never
        // block the UI or leave the popup stuck open.
        popup.colorVersion++
        popup.showCreateForm = false
        popup.visible = false

        // PrintessProfileManager is a global QML context property registered
        // by the PrintessAllMaterials plugin via engineCreatedSignal.
        // It saves the colour to UM.Preferences, duplicates the containers,
        // and activates the new profile after a 300 ms timer.
        try
        {
            profileManager.createTipProfile(
                name,
                Cura.MachineManager.activeQualityOrQualityChangesName,
                popup.createFormColor,
                popup.createFormLineWidth
            )
        }
        catch(e)
        {
            console.log("PrintessProfileManager.createTipProfile error: " + e)
        }
    }

    onVisibleChanged:
    {
        if (visible)
            colorVersion++  // Force delegate re-evaluation on every open
        else
            showCreateForm = false
    }

    Cura.PrintessProfileManager { id: profileManager }

    // ── Popup chrome ──────────────────────────────────────────────────────────
    topPadding: UM.Theme.getSize("narrow_margin").height
    rightPadding: UM.Theme.getSize("default_lining").width
    leftPadding: UM.Theme.getSize("default_lining").width
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    background: Cura.RoundedRectangle
    {
        color: backgroundColor
        border.width: UM.Theme.getSize("default_lining").width
        border.color: borderColor
        cornerSide: Cura.RoundedRectangle.Direction.Down
    }

    ButtonGroup
    {
        id: buttonGroup
        exclusive: true
        onClicked: popup.visible = false
    }

    // ── Content ───────────────────────────────────────────────────────────────
    contentItem: Column
    {
        // ── View 1: Tip list ──────────────────────────────────────────────────
        ScrollView
        {
            id: qualityListScrollView
            visible: !popup.showCreateForm
            property real maximumHeight: screenScaleFactor * 400
            contentHeight: dataColumn.height
            height: visible ? Math.min(contentHeight, maximumHeight) : 0
            width: parent.width

            clip: true
            ScrollBar.vertical: UM.ScrollBar
            {
                id: qualityListScrollBar
                parent: qualityListScrollView
                anchors { top: parent.top; right: parent.right; bottom: parent.bottom }
            }

            Column
            {
                id: dataColumn
                width: qualityListScrollView.width - qualityListScrollBar.width

                Item
                {
                    height: childrenRect.height
                    width: dataColumn.width

                    UM.Label
                    {
                        id: customProfileHeader
                        text: catalog.i18nc("@label:header", "Dispense Tip Options")
                        height: visible ? contentHeight : 0
                        enabled: false
                        visible: profilesList.visibleChildren.length > 1
                        anchors.left: parent.left
                        anchors.leftMargin: UM.Theme.getSize("default_margin").width
                        color: UM.Theme.getColor("text_inactive")
                    }

                    Column
                    {
                        id: profilesList
                        anchors { top: customProfileHeader.bottom; left: parent.left; right: parent.right }

                        Binding
                        {
                            target: parent
                            property: "height"
                            value: parent.childrenRect.height
                            when: parent.visibleChildren.length > 1
                        }

                        Repeater
                        {
                            model: CuraApplication.getCustomQualityProfilesDropDownMenuModel()
                            MenuButton
                            {
                                width: parent.width
                                checkable: true
                                visible: true
                                text: model.name
                                tipColor:
                                {
                                    // colorVersion dependency forces re-evaluation on every popup open
                                    var _ = popup.colorVersion
                                    var c = popup.tipColorMap[model.name]
                                    if (c !== undefined) return c
                                    c = popup.getCustomTipColor(model.name)
                                    return c !== "" ? c : "transparent"
                                }
                                leftPadding: UM.Theme.getSize("default_margin").width + UM.Theme.getSize("narrow_margin").width
                                checked:
                                {
                                    var ag = Cura.MachineManager.activeQualityChangesGroup
                                    return ag != null && ag.name == model.quality_changes_group.name
                                }
                                ButtonGroup.group: buttonGroup
                                onClicked:
                                {
                                    Cura.ContainerManager.updateQualityChanges()
                                    Cura.ContainerManager.clearUserContainers()
                                    Cura.MachineManager.setQualityChangesGroup(model.quality_changes_group)
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle
        {
            visible: !popup.showCreateForm
            height: visible ? UM.Theme.getSize("default_lining").height : 0
            anchors.left: parent.left
            anchors.right: parent.right
            color: borderColor
        }

        MenuButton
        {
            id: createNewTipButton
            visible: !popup.showCreateForm
            text: catalog.i18nc("@action:button", "Create New Dispense Tip...")
            anchors { left: parent.left; right: parent.right }
            height: visible ? (createNewTipLabel.contentHeight + UM.Theme.getSize("default_margin").height) : 0

            contentItem: Item
            {
                width: parent.width; height: parent.height
                UM.Label
                {
                    id: createNewTipLabel
                    text: createNewTipButton.text
                    height: contentHeight
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            onClicked:
            {
                tipNameField.text = ""
                lineWidthField.text = ""
                popup.createFormColor = "#E53935"
                popup.createFormLineWidth = 0.0
                popup.showCreateForm = true
                Qt.callLater(function() { tipNameField.forceActiveFocus() })
            }
        }

        Rectangle
        {
            visible: !popup.showCreateForm
            height: visible ? UM.Theme.getSize("default_lining").height : 0
            anchors.left: parent.left
            anchors.right: parent.right
            color: borderColor
        }

        MenuButton
        {
            id: manageProfilesButton
            visible: !popup.showCreateForm
            text: catalog.i18nc("@action:button", "Manage Dispense Tips...")
            anchors { left: parent.left; right: parent.right }
            height: visible ? (textLabel.contentHeight + UM.Theme.getSize("default_margin").height) : 0

            contentItem: Item
            {
                width: parent.width; height: parent.height
                UM.Label
                {
                    id: textLabel
                    text: manageProfilesButton.text
                    height: contentHeight
                    anchors.verticalCenter: parent.verticalCenter
                }
                UM.Label
                {
                    id: shortcutLabel
                    text: Cura.Actions.manageProfiles.shortcut
                    color: UM.Theme.getColor("text_lighter")
                    height: contentHeight
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right
                    anchors.rightMargin: UM.Theme.getSize("default_margin").width
                }
            }
            onClicked:
            {
                popup.visible = false
                Cura.Actions.manageProfiles.trigger()
            }
        }

        Item
        {
            visible: !popup.showCreateForm
            width: 2
            height: visible ? UM.Theme.getSize("default_radius").width : 0
        }

        // ── View 2: Create form ───────────────────────────────────────────────
        Item
        {
            visible: popup.showCreateForm
            width: parent.width
            height: visible ? (formColumn.height + UM.Theme.getSize("default_margin").height * 2) : 0

            Column
            {
                id: formColumn
                x: UM.Theme.getSize("default_margin").width
                y: UM.Theme.getSize("default_margin").height
                width: parent.width - UM.Theme.getSize("default_margin").width * 2
                spacing: UM.Theme.getSize("narrow_margin").height

                Item
                {
                    width: parent.width
                    height: Math.max(formTitle.contentHeight, backButton.implicitHeight)

                    UM.Label
                    {
                        id: formTitle
                        text: catalog.i18nc("@label", "Create New Dispense Tip")
                        font: UM.Theme.getFont("medium_bold")
                        anchors.left: parent.left
                        anchors.right: backButton.left
                        anchors.rightMargin: UM.Theme.getSize("narrow_margin").width
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                    }

                    Button
                    {
                        id: backButton
                        text: "✕"
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: popup.showCreateForm = false
                    }
                }

                Rectangle
                {
                    width: parent.width
                    height: UM.Theme.getSize("default_lining").height
                    color: borderColor
                }

                UM.Label
                {
                    text: catalog.i18nc("@label", "Name")
                    width: parent.width
                }

                TextField
                {
                    id: tipNameField
                    width: parent.width
                    placeholderText: catalog.i18nc("@placeholder", "e.g. My 0.5mm Custom Tip")
                    Keys.onReturnPressed: popup.doCreate()
                }

                UM.Label
                {
                    text: catalog.i18nc("@label", "Nozzle Diameter (mm)")
                    width: parent.width
                }

                TextField
                {
                    id: lineWidthField
                    width: parent.width
                    placeholderText: catalog.i18nc("@placeholder", "e.g. 0.5  (leave blank to copy from current tip)")
                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                    validator: DoubleValidator { bottom: 0.01; top: 99.0; decimals: 4; notation: DoubleValidator.StandardNotation }
                    onTextChanged:
                    {
                        var v = parseFloat(text)
                        popup.createFormLineWidth = (!isNaN(v) && acceptableInput && v > 0) ? v : 0.0
                    }
                    Keys.onReturnPressed: popup.doCreate()
                }

                UM.Label
                {
                    text: catalog.i18nc("@label", "Color")
                    width: parent.width
                }

                Grid
                {
                    id: colorGrid
                    columns: 6
                    spacing: UM.Theme.getSize("narrow_margin").width
                    width: parent.width

                    Repeater
                    {
                        model: popup.colorPalette
                        Rectangle
                        {
                            property int sw: Math.floor((colorGrid.width - colorGrid.spacing * 5) / 6)
                            width: sw
                            height: sw
                            radius: 4
                            color: modelData
                            border.width: modelData === popup.createFormColor ? 3 : 1
                            border.color: modelData === popup.createFormColor
                                ? UM.Theme.getColor("primary")
                                : UM.Theme.getColor("lining")
                            MouseArea
                            {
                                anchors.fill: parent
                                onClicked: popup.createFormColor = modelData
                                cursorShape: Qt.PointingHandCursor
                            }
                        }
                    }
                }

                Row
                {
                    width: parent.width
                    spacing: UM.Theme.getSize("narrow_margin").width

                    Rectangle
                    {
                        property int h: Math.round(previewLabel.contentHeight * 0.85)
                        width: Math.round(h * 1.6)
                        height: h
                        radius: h / 2
                        color: popup.createFormColor
                        border.width: popup.createFormColor === "#FFFFFF" ? 1 : 0
                        border.color: "#888888"
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    UM.Label
                    {
                        id: previewLabel
                        text: tipNameField.text !== ""
                            ? tipNameField.text
                            : catalog.i18nc("@label", "(enter a name above)")
                        color: tipNameField.text !== ""
                            ? UM.Theme.getColor("text")
                            : UM.Theme.getColor("text_inactive")
                        elide: Text.ElideRight
                        width: parent.width - Math.round(contentHeight * 0.85 * 1.6) - parent.spacing
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Rectangle
                {
                    width: parent.width
                    height: UM.Theme.getSize("default_lining").height
                    color: borderColor
                }

                Rectangle
                {
                    width: parent.width
                    height: createLabel.contentHeight + UM.Theme.getSize("default_margin").height
                    radius: UM.Theme.getSize("default_radius").width
                    color: tipNameField.text.trim() !== ""
                        ? UM.Theme.getColor("primary")
                        : UM.Theme.getColor("background_2")

                    UM.Label
                    {
                        id: createLabel
                        text: catalog.i18nc("@action:button", "Create Dispense Tip")
                        anchors.centerIn: parent
                        color: tipNameField.text.trim() !== "" ? "#FFFFFF" : UM.Theme.getColor("text_inactive")
                        font: UM.Theme.getFont("medium_bold")
                    }

                    MouseArea
                    {
                        anchors.fill: parent
                        cursorShape: tipNameField.text.trim() !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: { if (tipNameField.text.trim() !== "") popup.doCreate() }
                    }
                }

                Item { width: 1; height: UM.Theme.getSize("narrow_margin").height }
            }
        }
    }
}
