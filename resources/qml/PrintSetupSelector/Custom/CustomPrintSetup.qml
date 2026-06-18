//Copyright (c) 2022 Ultimaker B.V.
//Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.10
import QtQuick.Controls 2.3
import QtQuick.Layouts 1.3
import QtQuick.Window 2.2

import UM 1.5 as UM
import Cura 1.6 as Cura
import ".."

Item
{
    id: customPrintSetup

    property real padding: UM.Theme.getSize("default_margin").width
    property bool multipleExtruders: extrudersModel.count > 1

    property var extrudersModel: CuraApplication.getExtrudersModel()

    // Auto-save: persist setting changes into the active profile the moment the
    // user clicks away from a field.
    property bool _autoSaving: false

    Connections
    {
        target: customPrintSetup.Window.window
        function onActiveFocusItemChanged()
        {
            Qt.callLater(function()
            {
                if (!customPrintSetup._autoSaving && Cura.MachineManager.hasUserSettings)
                {
                    customPrintSetup._autoSaving = true
                    Cura.ContainerManager.updateQualityChanges()
                    customPrintSetup._autoSaving = false
                }
            })
        }
    }

    // ── Tip data ──────────────────────────────────────────────────────────────

    readonly property var tipDataMap: ({
        "Nordson Olive 1.54mm ID":    { lineWidth: 1.54, layerHeight: 1.54 },
        "Nordson Amber 1.36mm ID":    { lineWidth: 1.36, layerHeight: 1.36 },
        "Nordson Green 0.84mm ID":    { lineWidth: 0.84, layerHeight: 0.84 },
        "Nordson Pink 0.61mm ID":     { lineWidth: 0.61, layerHeight: 0.61 },
        "Nordson Purple 0.51mm ID":   { lineWidth: 0.51, layerHeight: 0.51 },
        "Nordson Blue 0.41mm ID":     { lineWidth: 0.41, layerHeight: 0.41 },
        "Nordson Orange 0.33mm ID":   { lineWidth: 0.33, layerHeight: 0.33 },
        "Nordson Red 0.25mm ID":      { lineWidth: 0.25, layerHeight: 0.25 },
        "Nordson Clear 0.20mm ID":    { lineWidth: 0.20, layerHeight: 0.20 },
        "Nordson Lavender 0.15mm ID": { lineWidth: 0.15, layerHeight: 0.15 },
        "Nordson Yellow 0.10mm ID":   { lineWidth: 0.10, layerHeight: 0.10 }
    })

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

    // ── Setting providers ─────────────────────────────────────────────────────

    UM.SettingPropertyProvider
    {
        id: e1LineWidthProvider
        containerStack: Cura.MachineManager.activeMachine ? Cura.MachineManager.activeMachine.extruderList[0] : null
        key: "line_width"
        watchedProperties: ["value"]
    }

    UM.SettingPropertyProvider
    {
        id: e2LineWidthProvider
        containerStack: Cura.MachineManager.activeMachine ? Cura.MachineManager.activeMachine.extruderList[1] : null
        key: "line_width"
        watchedProperties: ["value"]
    }

    UM.SettingPropertyProvider
    {
        id: globalLayerHeight
        containerStack: Cura.MachineManager.activeMachine
        key: "layer_height"
        watchedProperties: ["value"]
    }

    UM.SettingPropertyProvider
    {
        id: globalLayerHeight0
        containerStack: Cura.MachineManager.activeMachine
        key: "layer_height_0"
        watchedProperties: ["value"]
    }

    UM.SettingPropertyProvider
    {
        id: globalRetractionCombing
        containerStack: Cura.MachineManager.activeMachine
        key: "retraction_combing"
        watchedProperties: ["value"]
    }

    UM.SettingPropertyProvider
    {
        id: retractBeforeTravelE1Provider
        containerStack: Cura.MachineManager.activeMachine ? Cura.MachineManager.activeMachine.extruderList[0] : null
        key: "printess_retract_before_travel"
        watchedProperties: ["value", "enabled"]
        storeIndex: 0
    }

    UM.SettingPropertyProvider
    {
        id: retractBeforeTravelE2Provider
        containerStack: Cura.MachineManager.activeMachine ? Cura.MachineManager.activeMachine.extruderList[1] : null
        key: "printess_retract_before_travel"
        watchedProperties: ["value", "enabled"]
        storeIndex: 0
    }

    // Auto-deselect each extruder's "Retract Before Travel" when its retraction is disabled.
    Connections
    {
        target: retractBeforeTravelE1Provider
        function onPropertiesChanged()
        {
            if (!retractBeforeTravelE1Provider.properties.enabled && retractBeforeTravelE1Provider.properties.value)
                retractBeforeTravelE1Provider.setPropertyValue("value", false)
        }
    }

    Connections
    {
        target: retractBeforeTravelE2Provider
        function onPropertiesChanged()
        {
            if (!retractBeforeTravelE2Provider.properties.enabled && retractBeforeTravelE2Provider.properties.value)
                retractBeforeTravelE2Provider.setPropertyValue("value", false)
        }
    }

    // ── Python reset manager ──────────────────────────────────────────────────
    Cura.PrintessProfileManager { id: resetManager }

    // Reset one extruder's settings to the active tip's install defaults.
    function doReset(extruderIndex)
    {
        resetManager.resetTipToDefaults(extruderIndex, Cura.MachineManager.activeQualityOrQualityChangesName)
    }

    // ── Mirror direction dialog ───────────────────────────────────────────────

    Dialog
    {
        id: mirrorDialog
        title: catalog.i18nc("@title:window", "Mirror Extruder Settings")
        modal: true
        closePolicy: Popup.CloseOnEscape
        standardButtons: Dialog.NoButton
        anchors.centerIn: parent

        Column
        {
            spacing: UM.Theme.getSize("default_margin").height
            width: 400

            UM.Label
            {
                width: parent.width
                wrapMode: Text.WordWrap
                text: catalog.i18nc("@label", "Select which extruder's settings to copy onto the other. This will overwrite the destination extruder's current settings.")
            }

            // Direction option buttons
            Row
            {
                spacing: UM.Theme.getSize("default_margin").width
                anchors.horizontalCenter: parent.horizontalCenter

                // E1 → E2
                Rectangle
                {
                    id: mirrorE1toE2Rect
                    width: 180
                    height: mirrorE1toE2Col.implicitHeight + 2 * UM.Theme.getSize("default_margin").height
                    color: mirrorE1toE2Area.containsMouse ? UM.Theme.getColor("primary").lighter(1.9) : "transparent"
                    border.width: UM.Theme.getSize("default_lining").width
                    border.color: mirrorE1toE2Area.containsMouse ? UM.Theme.getColor("primary") : UM.Theme.getColor("lining")
                    radius: UM.Theme.getSize("checkbox_radius").width

                    Column
                    {
                        id: mirrorE1toE2Col
                        anchors.centerIn: parent
                        spacing: UM.Theme.getSize("narrow_margin").height

                        Row
                        {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: UM.Theme.getSize("narrow_margin").width

                            Cura.ExtruderIcon
                            {
                                materialColor: extrudersModel.count > 0 ? extrudersModel.getItem(0).color : "#888888"
                                extruderEnabled: extrudersModel.count > 0 ? extrudersModel.getItem(0).enabled : true
                                text: "1"
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            UM.Label
                            {
                                text: "→"
                                font: UM.Theme.getFont("medium")
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            Cura.ExtruderIcon
                            {
                                materialColor: extrudersModel.count > 1 ? extrudersModel.getItem(1).color : "#888888"
                                extruderEnabled: extrudersModel.count > 1 ? extrudersModel.getItem(1).enabled : true
                                text: "2"
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        UM.Label
                        {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: catalog.i18nc("@action:button", "Copy E1 onto E2")
                            font: UM.Theme.getFont("default")
                            color: mirrorE1toE2Area.containsMouse ? UM.Theme.getColor("primary") : UM.Theme.getColor("text")
                        }
                    }

                    MouseArea
                    {
                        id: mirrorE1toE2Area
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked:
                        {
                            resetManager.mirrorExtruder(0, 1)
                            mirrorDialog.accept()
                        }
                    }
                }

                // E2 → E1
                Rectangle
                {
                    id: mirrorE2toE1Rect
                    width: 180
                    height: mirrorE2toE1Col.implicitHeight + 2 * UM.Theme.getSize("default_margin").height
                    color: mirrorE2toE1Area.containsMouse ? UM.Theme.getColor("primary").lighter(1.9) : "transparent"
                    border.width: UM.Theme.getSize("default_lining").width
                    border.color: mirrorE2toE1Area.containsMouse ? UM.Theme.getColor("primary") : UM.Theme.getColor("lining")
                    radius: UM.Theme.getSize("checkbox_radius").width

                    Column
                    {
                        id: mirrorE2toE1Col
                        anchors.centerIn: parent
                        spacing: UM.Theme.getSize("narrow_margin").height

                        Row
                        {
                            anchors.horizontalCenter: parent.horizontalCenter
                            spacing: UM.Theme.getSize("narrow_margin").width

                            Cura.ExtruderIcon
                            {
                                materialColor: extrudersModel.count > 1 ? extrudersModel.getItem(1).color : "#888888"
                                extruderEnabled: extrudersModel.count > 1 ? extrudersModel.getItem(1).enabled : true
                                text: "2"
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            UM.Label
                            {
                                text: "→"
                                font: UM.Theme.getFont("medium")
                                anchors.verticalCenter: parent.verticalCenter
                            }

                            Cura.ExtruderIcon
                            {
                                materialColor: extrudersModel.count > 0 ? extrudersModel.getItem(0).color : "#888888"
                                extruderEnabled: extrudersModel.count > 0 ? extrudersModel.getItem(0).enabled : true
                                text: "1"
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        UM.Label
                        {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: catalog.i18nc("@action:button", "Copy E2 onto E1")
                            font: UM.Theme.getFont("default")
                            color: mirrorE2toE1Area.containsMouse ? UM.Theme.getColor("primary") : UM.Theme.getColor("text")
                        }
                    }

                    MouseArea
                    {
                        id: mirrorE2toE1Area
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked:
                        {
                            resetManager.mirrorExtruder(1, 0)
                            mirrorDialog.accept()
                        }
                    }
                }
            }

            Cura.SecondaryButton
            {
                anchors.horizontalCenter: parent.horizontalCenter
                text: catalog.i18nc("@action:button", "Cancel")
                onClicked: mirrorDialog.reject()
            }
        }
    }

    // ── Reset confirmation dialog ─────────────────────────────────────────────

    Dialog
    {
        id: resetDialog
        property int extruderIndex: 0

        title: catalog.i18nc("@title:window", "Reset to Default Values")
        modal: true
        closePolicy: Popup.CloseOnEscape
        standardButtons: Dialog.NoButton
        anchors.centerIn: parent

        Column
        {
            spacing: UM.Theme.getSize("default_margin").height
            width: 400

            UM.Label
            {
                width: parent.width
                wrapMode: Text.WordWrap
                text: catalog.i18nc("@label",
                    "This will restore all of Extruder %1's settings to the factory defaults for <b>%2</b>, including line width, print speed, infill density, and retraction settings.<br/><br/>Any changes you have made to this extruder will be overwritten.")
                    .arg(resetDialog.extruderIndex + 1)
                    .arg(Cura.MachineManager.activeQualityOrQualityChangesName)
            }

            Row
            {
                spacing: UM.Theme.getSize("default_margin").width
                anchors.horizontalCenter: parent.horizontalCenter

                Cura.SecondaryButton
                {
                    text: catalog.i18nc("@action:button", "Cancel")
                    onClicked: resetDialog.reject()
                }

                Cura.PrimaryButton
                {
                    text: catalog.i18nc("@action:button", "Reset")
                    onClicked:
                    {
                        doReset(resetDialog.extruderIndex)
                        resetDialog.accept()
                    }
                }
            }
        }
    }

    // ── Settings info banner ──────────────────────────────────────────────────

    Rectangle
    {
        id: warningBanner

        anchors
        {
            top: parent.top
            topMargin: UM.Theme.getSize("default_margin").height
            left: parent.left
            leftMargin: parent.padding
            right: parent.right
            rightMargin: parent.padding
        }

        height: bannerText.implicitHeight + 2 * UM.Theme.getSize("narrow_margin").height
        color: Qt.rgba(25 / 255, 110 / 255, 240 / 255, 0.07)
        border.color: UM.Theme.getColor("accent_1")
        border.width: UM.Theme.getSize("default_lining").width
        radius: UM.Theme.getSize("checkbox_radius").width

        UM.ColorImage
        {
            id: bannerIcon
            anchors
            {
                left: parent.left
                leftMargin: UM.Theme.getSize("default_margin").width
                top: parent.top
                topMargin: UM.Theme.getSize("narrow_margin").height
            }
            width: UM.Theme.getSize("small_button_icon").width
            height: UM.Theme.getSize("small_button_icon").height
            source: UM.Theme.getIcon("Information")
            color: UM.Theme.getColor("accent_1")
        }

        UM.Label
        {
            id: bannerText
            anchors
            {
                top: parent.top
                topMargin: UM.Theme.getSize("narrow_margin").height
                left: bannerIcon.right
                leftMargin: UM.Theme.getSize("narrow_margin").width
                right: parent.right
                rightMargin: UM.Theme.getSize("default_margin").width
            }
            text: "Printessa Series print settings are designed to operate in conjunction with the Printess post-processing scripts. Modifying settings outside the Printessa Series profile may adversely affect G-code generation and produce unintended print behavior."
            font: UM.Theme.getFont("small")
            color: UM.Theme.getColor("text")
            wrapMode: Text.WordWrap
        }
    }

    // ── Tip selector section ──────────────────────────────────────────────────

    Item
    {
        id: tipSelectorSection
        height: childrenRect.height

        anchors
        {
            top: warningBanner.bottom
            topMargin: UM.Theme.getSize("default_margin").height
            left: parent.left
            leftMargin: parent.padding
            right: parent.right
            rightMargin: parent.padding
        }

        // "Dispense Tip" label + Mirror button on the same row
        RowLayout
        {
            id: tipHeaderRow
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right

            UM.Label
            {
                id: tipLabel
                text: catalog.i18nc("@label", "Dispense Tip")
                font: UM.Theme.getFont("medium")
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
            }

            Rectangle
            {
                id: mirrorButton
                visible: multipleExtruders
                Layout.alignment: Qt.AlignVCenter
                width: mirrorBtnLayout.implicitWidth + 2 * UM.Theme.getSize("narrow_margin").width
                height: mirrorBtnLayout.implicitHeight + UM.Theme.getSize("narrow_margin").height
                color: "transparent"
                border.width: UM.Theme.getSize("default_lining").width
                border.color: mirrorButtonArea.containsMouse ? UM.Theme.getColor("primary") : UM.Theme.getColor("lining")
                radius: UM.Theme.getSize("checkbox_radius").width

                RowLayout
                {
                    id: mirrorBtnLayout
                    anchors.centerIn: parent
                    spacing: UM.Theme.getSize("narrow_margin").width

                    UM.Label
                    {
                        text: catalog.i18nc("@action:button", "Mirror")
                        font: UM.Theme.getFont("default")
                        color: mirrorButtonArea.containsMouse ? UM.Theme.getColor("primary") : UM.Theme.getColor("text_medium")
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Cura.ExtruderIcon
                    {
                        materialColor: extrudersModel.count > 0 ? extrudersModel.getItem(0).color : "#888888"
                        extruderEnabled: extrudersModel.count > 0 ? extrudersModel.getItem(0).enabled : true
                        text: "1"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    UM.Label
                    {
                        text: "⇄"
                        font: UM.Theme.getFont("default")
                        color: mirrorButtonArea.containsMouse ? UM.Theme.getColor("primary") : UM.Theme.getColor("text_medium")
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Cura.ExtruderIcon
                    {
                        materialColor: extrudersModel.count > 1 ? extrudersModel.getItem(1).color : "#888888"
                        extruderEnabled: extrudersModel.count > 1 ? extrudersModel.getItem(1).enabled : true
                        text: "2"
                        Layout.alignment: Qt.AlignVCenter
                    }
                }

                MouseArea
                {
                    id: mirrorButtonArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: mirrorDialog.open()
                }
            }
        }

        Button
        {
            id: tipDropdownButton
            anchors.top: tipHeaderRow.bottom
            anchors.topMargin: UM.Theme.getSize("narrow_margin").height
            anchors.left: parent.left
            anchors.right: parent.right

            height: tipTextLabel.contentHeight + 2 * UM.Theme.getSize("narrow_margin").height
            hoverEnabled: true

            onClicked: tipMenu.opened ? tipMenu.close() : tipMenu.open()

            contentItem: Item
            {
                anchors.fill: parent
                anchors.leftMargin: UM.Theme.getSize("default_margin").width
                anchors.rightMargin: UM.Theme.getSize("default_margin").width

                UM.Label
                {
                    id: tipTextLabel
                    anchors.left: parent.left
                    anchors.right: tipOval.left
                    anchors.rightMargin: UM.Theme.getSize("narrow_margin").width
                    anchors.verticalCenter: parent.verticalCenter
                    text: Cura.MachineManager.activeQualityOrQualityChangesName
                    elide: Text.ElideRight
                    wrapMode: Text.NoWrap
                }

                Rectangle
                {
                    id: tipOval
                    property string activeName: Cura.MachineManager.activeQualityOrQualityChangesName
                    property string resolvedColor:
                    {
                        var c = tipColorMap[activeName]
                        if (c !== undefined) return c
                        return customPrintSetup.getCustomTipColor(activeName)
                    }
                    width: resolvedColor !== "" ? Math.round(height * 1.6) : 0
                    height: Math.round(tipTextLabel.contentHeight * 0.85)
                    radius: height / 2
                    color: resolvedColor !== "" ? resolvedColor : "transparent"
                    border.width: resolvedColor === "#FFFFFF" ? 1 : 0
                    border.color: "#888888"
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: tipArrow.left
                    anchors.rightMargin: UM.Theme.getSize("narrow_margin").width
                }

                UM.ColorImage
                {
                    id: tipArrow
                    source: UM.Theme.getIcon("ChevronSingleDown")
                    width: UM.Theme.getSize("standard_arrow").width
                    height: UM.Theme.getSize("standard_arrow").height
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    color: UM.Theme.getColor("setting_control_button")
                }
            }

            background: UM.UnderlineBackground
            {
                liningColor: tipDropdownButton.hovered
                    ? UM.Theme.getColor("text_field_border_hovered")
                    : UM.Theme.getColor("border_field_light")
            }
        }

        // Nordson-only reset buttons. Wrapped in a collapsing Item so no empty
        // space appears when a custom tip is active.
        Item
        {
            id: nordsonButtonRow
            anchors.top: tipDropdownButton.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            // Collapse completely when a custom tip is active.
            visible: tipDataMap[Cura.MachineManager.activeQualityOrQualityChangesName] !== undefined
            height: visible ? childrenRect.height + UM.Theme.getSize("narrow_margin").height : 0

            Button
            {
                id: e1ResetButton
                anchors.top: parent.top
                anchors.topMargin: UM.Theme.getSize("narrow_margin").height
                anchors.left: parent.left
                anchors.right: parent.horizontalCenter
                anchors.rightMargin: UM.Theme.getSize("default_margin").width / 2
                hoverEnabled: true
                padding: UM.Theme.getSize("narrow_margin").width

                contentItem: UM.Label
                {
                    text: catalog.i18nc("@action:button", "Reset Extruder 1 Print Settings to Default for Selected Dispense Tip.")
                    color: e1ResetButton.hovered ? UM.Theme.getColor("primary") : UM.Theme.getColor("text_medium")
                    font: UM.Theme.getFont("default")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }

                background: Rectangle
                {
                    color: "transparent"
                    border.width: UM.Theme.getSize("default_lining").width
                    border.color: e1ResetButton.hovered ? UM.Theme.getColor("primary") : UM.Theme.getColor("lining")
                    radius: UM.Theme.getSize("checkbox_radius").width
                }

                onClicked:
                {
                    resetDialog.extruderIndex = 0
                    resetDialog.open()
                }
            }

            Button
            {
                id: e2ResetButton
                anchors.top: parent.top
                anchors.topMargin: UM.Theme.getSize("narrow_margin").height
                anchors.left: parent.horizontalCenter
                anchors.leftMargin: UM.Theme.getSize("default_margin").width / 2
                anchors.right: parent.right
                hoverEnabled: true
                padding: UM.Theme.getSize("narrow_margin").width

                contentItem: UM.Label
                {
                    text: catalog.i18nc("@action:button", "Reset Extruder 2 Print Settings to Default for Selected Dispense Tip.")
                    color: e2ResetButton.hovered ? UM.Theme.getColor("primary") : UM.Theme.getColor("text_medium")
                    font: UM.Theme.getFont("default")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }

                background: Rectangle
                {
                    color: "transparent"
                    border.width: UM.Theme.getSize("default_lining").width
                    border.color: e2ResetButton.hovered ? UM.Theme.getColor("primary") : UM.Theme.getColor("lining")
                    radius: UM.Theme.getSize("checkbox_radius").width
                }

                onClicked:
                {
                    resetDialog.extruderIndex = 1
                    resetDialog.open()
                }
            }
        }

        QualitiesWithIntentMenu
        {
            id: tipMenu
            x: tipDropdownButton.x
            y: tipDropdownButton.y + tipDropdownButton.height
        }
    }

    // ── Extruder tab bar ──────────────────────────────────────────────────────

    UM.TabRow
    {
        id: tabBar

        visible: multipleExtruders

        anchors
        {
            top: tipSelectorSection.bottom
            topMargin: UM.Theme.getSize("default_margin").height
            left: parent.left
            leftMargin: parent.padding
            right: parent.right
            rightMargin: parent.padding
        }

        Repeater
        {
            id: repeater
            model: extrudersModel
            delegate: UM.TabRowButton
            {
                checked: model.index == 0
                contentItem: Item
                {
                    Cura.ExtruderIcon
                    {
                        anchors.centerIn: parent
                        materialColor: model.color
                        extruderEnabled: model.enabled
                        iconVariant: "default"
                    }
                }
                onClicked:
                {
                    Cura.ExtruderManager.setActiveExtruderIndex(tabBar.currentIndex)
                }
            }
        }

        Connections
        {
            target: Cura.ExtruderManager
            function onActiveExtruderChanged()
            {
                tabBar.setCurrentIndex(Cura.ExtruderManager.activeExtruderIndex);
            }
        }

        Connections
        {
            target: repeater.model
            function onModelChanged()
            {
                tabBar.setCurrentIndex(Cura.ExtruderManager.activeExtruderIndex)
            }
        }
    }

    Rectangle
    {
        anchors
        {
            top: tabBar.bottom
            topMargin: -UM.Theme.getSize("default_lining").width
            left: parent.left
            leftMargin: parent.padding
            right: parent.right
            rightMargin: parent.padding
            bottom: parent.bottom
        }
        z: tabBar.z - 1

        border.color: tabBar.visible ? UM.Theme.getColor("lining") : "transparent"
        border.width: UM.Theme.getSize("default_lining").width

        color: UM.Theme.getColor("main_background")

        opacity: Cura.MachineManager.activeStack != null && !Cura.MachineManager.activeStack.isEnabled ? 0.4 : 1.0

        Cura.SettingView
        {
            anchors
            {
                fill: parent
                topMargin: UM.Theme.getSize("default_margin").height
                leftMargin: UM.Theme.getSize("default_margin").width
                rightMargin: UM.Theme.getSize("narrow_margin").width
                bottomMargin: UM.Theme.getSize("default_lining").width
            }
        }
    }
}
