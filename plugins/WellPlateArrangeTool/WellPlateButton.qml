// Copyright (c) 2025 Printess Technologies
// Released under the terms of the LGPLv3 or higher.

import QtQuick 2.10
import QtQuick.Controls 2.3
import UM 1.7 as UM
import Cura 1.7 as Cura

Item
{
    id: base

    implicitHeight: UM.Theme.getSize("button").height
    implicitWidth:  btnRow.implicitWidth + UM.Theme.getSize("default_margin").width * 2

    // Layout constants used by popup content
    readonly property int  panelW:   220
    readonly property real halfGap:  Math.round(UM.Theme.getSize("default_margin").width / 2)
    readonly property real ctrlH:    UM.Theme.getSize("setting_control").height
    readonly property real ctrlW:    UM.Theme.getSize("setting_control").width
    readonly property real presetBW: Math.floor((panelW - halfGap * 2) / 3)

    // Which preset is currently active ("Custom" when none of the standard presets match)
    readonly property string activePreset:
    {
        if (!wellPlateManager) return "Custom"
        var r = wellPlateManager.rows, c = wellPlateManager.cols
        var sx = wellPlateManager.spacingX, sy = wellPlateManager.spacingY
        if (r===2  && c===3  && Math.abs(sx-39.12)<0.01 && Math.abs(sy-39.12)<0.01) return "6-Well"
        if (r===3  && c===4  && Math.abs(sx-26.01)<0.01 && Math.abs(sy-26.01)<0.01) return "12-Well"
        if (r===4  && c===6  && Math.abs(sx-19.30)<0.01 && Math.abs(sy-19.30)<0.01) return "24-Well"
        if (r===6  && c===8  && Math.abs(sx-13.08)<0.01 && Math.abs(sy-13.08)<0.01) return "48-Well"
        return "Custom"
    }

    // ── Button ─────────────────────────────────────────────────────────────────
    Rectangle
    {
        anchors.fill: parent
        radius: UM.Theme.getSize("default_radius").width
        color: popup.opened || hoverArea.containsMouse
            ? UM.Theme.getColor("primary_button_hover")
            : UM.Theme.getColor("primary_button")

        Row
        {
            id: btnRow
            anchors.centerIn: parent
            spacing: base.halfGap

            UM.ColorImage
            {
                anchors.verticalCenter: parent.verticalCenter
                source: Qt.resolvedUrl("WellPlate.svg")
                width:  UM.Theme.getSize("button_icon").width
                height: UM.Theme.getSize("button_icon").height
                color:  UM.Theme.getColor("primary_button_text")
            }

            UM.Label
            {
                id: btnLabel
                anchors.verticalCenter: parent.verticalCenter
                text: "Well Plate Arranger"
                color: UM.Theme.getColor("primary_button_text")
                font: UM.Theme.getFont("medium_bold")
            }
        }

        MouseArea
        {
            id: hoverArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: popup.opened ? popup.close() : popup.open()
        }
    }

    // ── Popup ──────────────────────────────────────────────────────────────────
    Popup
    {
        id: popup

        y: -implicitHeight - UM.Theme.getSize("default_margin").height
        x: 0

        padding: UM.Theme.getSize("default_margin").width
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle
        {
            color:        UM.Theme.getColor("tool_panel_background")
            border.color: UM.Theme.getColor("lining")
            border.width: UM.Theme.getSize("default_lining").width
            radius:       UM.Theme.getSize("default_radius").width
        }

        contentItem: Column
        {
            width:   base.panelW
            spacing: UM.Theme.getSize("default_margin").height

            // ── Print Level Clearance reminder ────────────────────────────────
            Rectangle
            {
                width:  parent.width
                height: clearanceLabel.implicitHeight + base.halfGap * 2
                color:  UM.Theme.getColor("main_background")
                radius: UM.Theme.getSize("default_radius").width
                border.color: UM.Theme.getColor("primary_button")
                border.width: UM.Theme.getSize("default_lining").width * 2

                UM.Label
                {
                    id: clearanceLabel
                    anchors
                    {
                        left: parent.left; right: parent.right
                        verticalCenter: parent.verticalCenter
                        margins: base.halfGap
                    }
                    text: "Reminder: Set 'Print Level Clearance' high enough so the nozzle clears the well plate walls between moves."
                    color: UM.Theme.getColor("text")
                    wrapMode: Text.WordWrap
                    font: UM.Theme.getFont("default")
                }
            }

            // ── Presets ───────────────────────────────────────────────────────
            Column
            {
                width: parent.width
                spacing: base.halfGap

                UM.Label
                {
                    text: "Well Plate Preset"
                    font: UM.Theme.getFont("default_bold")
                }

                Row
                {
                    spacing: base.halfGap
                    Repeater { model: ["6-Well", "12-Well", "24-Well"]; delegate: presetBtn }
                }

                Row
                {
                    spacing: base.halfGap
                    Repeater { model: ["48-Well", "Custom"]; delegate: presetBtn }
                }
            }

            // ── Divider ───────────────────────────────────────────────────────
            Rectangle
            {
                width:  parent.width
                height: UM.Theme.getSize("default_lining").width
                color:  UM.Theme.getColor("lining")
            }

            // ── Grid Configuration ────────────────────────────────────────────
            Column
            {
                width: parent.width
                spacing: base.halfGap

                UM.Label
                {
                    text: "Grid Configuration"
                    font: UM.Theme.getFont("default_bold")
                }

                Grid
                {
                    columns: 2
                    columnSpacing: UM.Theme.getSize("default_margin").width
                    rowSpacing: base.halfGap

                    UM.Label { text: "Rows";      height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: rowsField
                        width: base.ctrlW; height: base.ctrlH
                        unit: ""
                        validator: IntValidator { bottom: 1; top: 999 }
                        onEditingFinished:
                        {
                            var v = parseInt(text)
                            if (!isNaN(v) && v >= 1) wellPlateManager.setRows(v)
                        }
                    }

                    UM.Label { text: "Columns";   height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: colsField
                        width: base.ctrlW; height: base.ctrlH
                        unit: ""
                        validator: IntValidator { bottom: 1; top: 999 }
                        onEditingFinished:
                        {
                            var v = parseInt(text)
                            if (!isNaN(v) && v >= 1) wellPlateManager.setCols(v)
                        }
                    }

                    UM.Label { text: "X Spacing"; height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: spacingXField
                        width: base.ctrlW; height: base.ctrlH
                        unit: "mm"
                        validator: UM.FloatValidator { maxBeforeDecimal: 5; maxAfterDecimal: 2 }
                        onEditingFinished:
                        {
                            var v = parseFloat(text.replace(",", "."))
                            if (!isNaN(v) && v > 0) wellPlateManager.setSpacingX(v)
                        }
                    }

                    UM.Label { text: "Y Spacing"; height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: spacingYField
                        width: base.ctrlW; height: base.ctrlH
                        unit: "mm"
                        validator: UM.FloatValidator { maxBeforeDecimal: 5; maxAfterDecimal: 2 }
                        onEditingFinished:
                        {
                            var v = parseFloat(text.replace(",", "."))
                            if (!isNaN(v) && v > 0) wellPlateManager.setSpacingY(v)
                        }
                    }
                }
            }

            // ── Overflow warning ──────────────────────────────────────────────
            Rectangle
            {
                visible: wellPlateManager.objectCount > 0 &&
                         wellPlateManager.objectCount > (wellPlateManager.rows * wellPlateManager.cols)
                width:  parent.width
                height: visible ? overflowLabel.implicitHeight + UM.Theme.getSize("default_margin").height : 0
                color:  UM.Theme.getColor("setting_validation_warning_background")
                radius: UM.Theme.getSize("default_radius").width
                border.color: UM.Theme.getColor("setting_validation_warning")
                border.width: UM.Theme.getSize("default_lining").width

                UM.Label
                {
                    id: overflowLabel
                    anchors
                    {
                        left: parent.left; right: parent.right
                        verticalCenter: parent.verticalCenter
                        margins: base.halfGap
                    }
                    text: "%1 objects on plate, only %2 wells (%3\xd7%4). Extra objects will overflow the grid."
                          .arg(wellPlateManager.objectCount)
                          .arg(wellPlateManager.rows * wellPlateManager.cols)
                          .arg(wellPlateManager.rows)
                          .arg(wellPlateManager.cols)
                    color: UM.Theme.getColor("text")
                    wrapMode: Text.WordWrap
                }
            }

            // ── Arrange button ────────────────────────────────────────────────
            Item
            {
                width:  parent.width
                height: arrangeBtn.height

                Cura.PrimaryButton
                {
                    id: arrangeBtn
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width - UM.Theme.getSize("default_margin").width * 2
                    text: "Arrange"
                    onClicked:
                    {
                        wellPlateManager.arrangeWellPlate()
                        popup.close()
                    }
                }
            }

            Item { width: 1; height: base.halfGap }
        }
    }

    // ── Preset button component ────────────────────────────────────────────────
    Component
    {
        id: presetBtn

        Button
        {
            // Clicking "Custom" is a no-op — it is a read-only indicator
            property bool sel: base.activePreset === modelData

            implicitWidth:  base.presetBW
            implicitHeight: base.ctrlH

            contentItem: Text
            {
                text: modelData
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment:   Text.AlignVCenter
                font: UM.Theme.getFont("default")
                color: sel
                    ? UM.Theme.getColor("primary_button_text")
                    : UM.Theme.getColor("text")
                clip: true
                leftPadding:  4
                rightPadding: 4
            }

            background: Rectangle
            {
                radius: UM.Theme.getSize("default_radius").width
                color: sel
                    ? UM.Theme.getColor("primary_button")
                    : (parent.hovered && modelData !== "Custom"
                        ? UM.Theme.getColor("primary_button_hover")
                        : UM.Theme.getColor("main_background"))
                border.color: sel
                    ? UM.Theme.getColor("primary_button")
                    : UM.Theme.getColor("lining")
                border.width: UM.Theme.getSize("default_lining").width
            }

            onClicked:
            {
                if (modelData !== "Custom")
                    wellPlateManager.setPreset(modelData)
            }
        }
    }

    // ── Bindings: Python → fields (only when field is not focused) ─────────────
    Binding { target: rowsField;     property: "text"; value: wellPlateManager.rows;                when: !rowsField.activeFocus }
    Binding { target: colsField;     property: "text"; value: wellPlateManager.cols;                when: !colsField.activeFocus }
    Binding { target: spacingXField; property: "text"; value: wellPlateManager.spacingX.toFixed(2); when: !spacingXField.activeFocus }
    Binding { target: spacingYField; property: "text"; value: wellPlateManager.spacingY.toFixed(2); when: !spacingYField.activeFocus }
}
