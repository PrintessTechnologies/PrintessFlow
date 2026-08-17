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

    // Layout constants used by popup content.
    // Hardcoded pixel numbers go through px(). Theme sizes (UM.Theme.getSize)
    // are already scaled for the display and rounded to a whole pixel by
    // Theme.py; bare numbers are not, so at 150% display scaling the fonts grew
    // by half and this popup did not, and the preset labels were being sliced
    // mid-letter by the clip on their Text.
    function px(n) { return Math.round(n * screenScaleFactor) }

    readonly property int  panelW:   base.px(220)
    readonly property real halfGap:  Math.round(UM.Theme.getSize("default_margin").width / 2)
    // int, not real. UM.Label renders NATIVELY on Windows (see UM/Label.qml),
    // and a glyph whose baseline lands on a half pixel is hinted against the
    // wrong grid, which reads as bent letters rather than merely soft ones.
    readonly property int  ctrlH:    Math.round(UM.Theme.getSize("setting_control").height)
    readonly property real ctrlW:    UM.Theme.getSize("setting_control").width
    readonly property real presetBW: Math.floor((panelW - halfGap * 2) / 3)

    // Which entry is selected ("6-Well" .. "48-Well" or "Custom"). Authoritative
    // value comes from Python so editing a field switches cleanly to Custom
    // without ever appearing to mutate a preset.
    readonly property string activePreset: wellPlateManager ? wellPlateManager.activePreset : "Custom"

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
                renderType: Text.QtRendering
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
                    renderType: Text.QtRendering
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
                    renderType: Text.QtRendering
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
                    renderType: Text.QtRendering
                    text: "Grid Configuration"
                    font: UM.Theme.getFont("default_bold")
                }

                Grid
                {
                    columns: 2
                    columnSpacing: UM.Theme.getSize("default_margin").width
                    rowSpacing: base.halfGap

                    UM.Label { renderType: Text.QtRendering; text: "Rows";      height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: rowsField
                        width: base.ctrlW; height: base.ctrlH
                        // Preset grids are fixed; only Custom is editable.
                        enabled: base.activePreset === "Custom"
                        unit: ""
                        validator: IntValidator { bottom: 1; top: 999 }
                        onEditingFinished:
                        {
                            var v = parseInt(text)
                            if (!isNaN(v) && v >= 1) wellPlateManager.setRows(v)
                        }
                    }

                    UM.Label { renderType: Text.QtRendering; text: "Columns";   height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: colsField
                        width: base.ctrlW; height: base.ctrlH
                        enabled: base.activePreset === "Custom"
                        unit: ""
                        validator: IntValidator { bottom: 1; top: 999 }
                        onEditingFinished:
                        {
                            var v = parseInt(text)
                            if (!isNaN(v) && v >= 1) wellPlateManager.setCols(v)
                        }
                    }

                    UM.Label { renderType: Text.QtRendering; text: "X Spacing"; height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: spacingXField
                        width: base.ctrlW; height: base.ctrlH
                        enabled: base.activePreset === "Custom"
                        unit: "mm"
                        validator: UM.FloatValidator { maxBeforeDecimal: 5; maxAfterDecimal: 2 }
                        onEditingFinished:
                        {
                            var v = parseFloat(text.replace(",", "."))
                            if (!isNaN(v) && v > 0) wellPlateManager.setSpacingX(v)
                        }
                    }

                    UM.Label { renderType: Text.QtRendering; text: "Y Spacing"; height: base.ctrlH; verticalAlignment: Text.AlignVCenter }
                    UM.TextFieldWithUnit
                    {
                        id: spacingYField
                        width: base.ctrlW; height: base.ctrlH
                        enabled: base.activePreset === "Custom"
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
                    renderType: Text.QtRendering
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
            // "Custom" is selectable: clicking it restores the saved Custom grid.
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
                // Elide rather than clip. Clipping cuts the label off in the
                // middle of a letter, which reads as a broken glyph rather than
                // as a button that is too small; an ellipsis says which it is.
                elide: Text.ElideRight
                leftPadding:  base.px(4)
                rightPadding: base.px(4)
            }

            background: Rectangle
            {
                radius: UM.Theme.getSize("default_radius").width
                color: sel
                    ? UM.Theme.getColor("primary_button")
                    : (parent.hovered
                        ? UM.Theme.getColor("primary_button_hover")
                        : UM.Theme.getColor("main_background"))
                border.color: sel
                    ? UM.Theme.getColor("primary_button")
                    : UM.Theme.getColor("lining")
                border.width: UM.Theme.getSize("default_lining").width
            }

            onClicked: wellPlateManager.setPreset(modelData)
        }
    }

    // ── Bindings: Python → fields (only when field is not focused) ─────────────
    Binding { target: rowsField;     property: "text"; value: wellPlateManager.rows;                when: !rowsField.activeFocus }
    Binding { target: colsField;     property: "text"; value: wellPlateManager.cols;                when: !colsField.activeFocus }
    Binding { target: spacingXField; property: "text"; value: wellPlateManager.spacingX.toFixed(2); when: !spacingXField.activeFocus }
    Binding { target: spacingYField; property: "text"; value: wellPlateManager.spacingY.toFixed(2); when: !spacingYField.activeFocus }
}
