// Copyright (c) 2025 Printess Technologies
// Released under the terms of the LGPLv3 or higher.

import QtQuick 2.2
import QtQuick.Controls 2.3
import UM 1.7 as UM
import Cura 1.7 as Cura

Item
{
    id: base
    width:  contentCol.width
    height: contentCol.height

    // ── State mirrored from Python ────────────────────────────────────────────
    property int  rows:     8
    property int  cols:     12
    property real spacingX: 9.0
    property real spacingY: 9.0
    property int  objectCount: 0

    property bool tooManyObjects: objectCount > 0 && objectCount > (rows * cols)

    // Which preset, if any, matches the current config
    readonly property string activePreset:
    {
        var r = rows, c = cols, sx = spacingX, sy = spacingY
        if (r === 2  && c === 3  && Math.abs(sx - 39.12) < 0.01 && Math.abs(sy - 39.12) < 0.01) return "6-Well"
        if (r === 3  && c === 4  && Math.abs(sx - 26.01) < 0.01 && Math.abs(sy - 26.01) < 0.01) return "12-Well"
        if (r === 4  && c === 6  && Math.abs(sx - 19.30) < 0.01 && Math.abs(sy - 19.30) < 0.01) return "24-Well"
        if (r === 6  && c === 8  && Math.abs(sx - 13.08) < 0.01 && Math.abs(sy - 13.08) < 0.01) return "48-Well"
        return ""
    }

    Timer { interval: 1000; running: true; repeat: true
        onTriggered: base.objectCount = (UM.Controller.properties.getValue("ObjectCount") || 0) }

    // ── Layout constants ──────────────────────────────────────────────────────
    // Hardcoded pixel numbers go through px(). Theme sizes (UM.Theme.getSize)
    // are already scaled for the display and rounded to a whole pixel by
    // Theme.py; bare numbers are not, so on a 150% display the fonts grew by
    // half and the panel did not. At 220 the three preset buttons are about 68
    // px each, and "12-Well" needs all of that at 100% alone: at 150% it was
    // being sliced by the clip below, mid-letter.
    function px(n) { return Math.round(n * screenScaleFactor) }

    readonly property int  panelWidth:    base.px(220)
    readonly property real halfMargin:    Math.round(UM.Theme.getSize("default_margin").width  / 2)
    readonly property real sectionSpacing: UM.Theme.getSize("default_margin").height
    // int, not real. UM.Label renders NATIVELY on Windows (see UM/Label.qml),
    // and a glyph whose baseline lands on a half pixel is hinted against the
    // wrong grid, which reads as bent letters rather than merely soft ones.
    readonly property int  controlHeight: Math.round(UM.Theme.getSize("setting_control").height)
    readonly property real controlWidth:  UM.Theme.getSize("setting_control").width

    // Preset button fixed width: 3 across with half-margin gaps
    readonly property real presetBtnW: Math.floor((panelWidth - 2 * halfMargin) / 3)

    // ── Root column ───────────────────────────────────────────────────────────
    Column
    {
        id: contentCol
        width: base.panelWidth
        spacing: base.sectionSpacing

        // ── SECTION: Presets ─────────────────────────────────────────────────
        Column
        {
            width: parent.width
            spacing: base.halfMargin

            UM.Label
            {
                renderType: Text.QtRendering
                text: "Well Plate Preset"
                font: UM.Theme.getFont("default_bold")
            }

            // Row 1: 6-Well · 12-Well · 24-Well
            Row
            {
                spacing: base.halfMargin
                Repeater
                {
                    model: ["6-Well", "12-Well", "24-Well"]
                    delegate: presetBtn
                }
            }

            // Row 2: 48-Well (left-aligned, same button width as row 1)
            Row
            {
                spacing: base.halfMargin
                Repeater
                {
                    model: ["48-Well"]
                    delegate: presetBtn
                }
            }
        }

        // ── Divider ──────────────────────────────────────────────────────────
        Rectangle
        {
            width: parent.width
            height: UM.Theme.getSize("default_lining").width
            color: UM.Theme.getColor("lining")
        }

        // ── SECTION: Grid Configuration ──────────────────────────────────────
        Column
        {
            width: parent.width
            spacing: base.halfMargin

            UM.Label
            {
                renderType: Text.QtRendering
                text: "Grid Configuration"
                font: UM.Theme.getFont("default_bold")
            }

            Grid
            {
                columns: 2
                columnSpacing: base.sectionSpacing
                rowSpacing: base.halfMargin

                UM.Label { renderType: Text.QtRendering; text: "Rows";      height: base.controlHeight; verticalAlignment: Text.AlignVCenter }
                UM.TextFieldWithUnit
                {
                    id: rowsField
                    width: base.controlWidth; height: base.controlHeight
                    unit: ""
                    validator: IntValidator { bottom: 1; top: 999 }
                    onEditingFinished:
                    {
                        var v = parseInt(text)
                        if (!isNaN(v) && v >= 1) UM.Controller.setProperty("Rows", v)
                    }
                }

                UM.Label { renderType: Text.QtRendering; text: "Columns";   height: base.controlHeight; verticalAlignment: Text.AlignVCenter }
                UM.TextFieldWithUnit
                {
                    id: colsField
                    width: base.controlWidth; height: base.controlHeight
                    unit: ""
                    validator: IntValidator { bottom: 1; top: 999 }
                    onEditingFinished:
                    {
                        var v = parseInt(text)
                        if (!isNaN(v) && v >= 1) UM.Controller.setProperty("Cols", v)
                    }
                }

                UM.Label { renderType: Text.QtRendering; text: "X Spacing"; height: base.controlHeight; verticalAlignment: Text.AlignVCenter }
                UM.TextFieldWithUnit
                {
                    id: spacingXField
                    width: base.controlWidth; height: base.controlHeight
                    unit: "mm"
                    validator: UM.FloatValidator { maxBeforeDecimal: 5; maxAfterDecimal: 2 }
                    onEditingFinished:
                    {
                        var v = parseFloat(text.replace(",", "."))
                        if (!isNaN(v) && v > 0) UM.Controller.setProperty("SpacingX", v)
                    }
                }

                UM.Label { renderType: Text.QtRendering; text: "Y Spacing"; height: base.controlHeight; verticalAlignment: Text.AlignVCenter }
                UM.TextFieldWithUnit
                {
                    id: spacingYField
                    width: base.controlWidth; height: base.controlHeight
                    unit: "mm"
                    validator: UM.FloatValidator { maxBeforeDecimal: 5; maxAfterDecimal: 2 }
                    onEditingFinished:
                    {
                        var v = parseFloat(text.replace(",", "."))
                        if (!isNaN(v) && v > 0) UM.Controller.setProperty("SpacingY", v)
                    }
                }
            }
        }

        // ── Warning: too many objects ─────────────────────────────────────────
        Rectangle
        {
            visible: base.tooManyObjects
            width:   parent.width
            height:  visible ? warningLabel.implicitHeight + base.sectionSpacing : 0
            color:   UM.Theme.getColor("setting_validation_warning_background")
            radius:  UM.Theme.getSize("default_radius").width
            border.color: UM.Theme.getColor("setting_validation_warning")
            border.width: UM.Theme.getSize("default_lining").width

            UM.Label
            {
                renderType: Text.QtRendering
                id: warningLabel
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
                          margins: base.halfMargin }
                text: "%1 objects on plate, only %2 wells (%3\xd7%4). Extra objects will overflow the grid."
                      .arg(base.objectCount).arg(base.rows * base.cols).arg(base.rows).arg(base.cols)
                color: UM.Theme.getColor("setting_validation_warning")
                wrapMode: Text.WordWrap
            }
        }

        // ── Arrange button (centered) ─────────────────────────────────────────
        Item
        {
            width:  parent.width
            height: arrangeBtn.height

            Cura.PrimaryButton
            {
                id: arrangeBtn
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width - base.sectionSpacing * 2
                text: "Arrange"
                onClicked: UM.Controller.triggerAction("arrangeWellPlate")
            }
        }

        // bottom breathing room
        Item { width: 1; height: base.halfMargin }
    }

    // ── Preset button component ───────────────────────────────────────────────
    Component
    {
        id: presetBtn
        Button
        {
            property bool sel: base.activePreset === modelData

            implicitWidth:  base.presetBtnW
            implicitHeight: base.controlHeight

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

            onClicked: UM.Controller.setProperty("Preset", modelData)
        }
    }

    // ── Bindings: Python → QML ────────────────────────────────────────────────
    Binding { target: base; property: "rows";     value: UM.Controller.properties.getValue("Rows")     || base.rows }
    Binding { target: base; property: "cols";     value: UM.Controller.properties.getValue("Cols")     || base.cols }
    Binding { target: base; property: "spacingX"; value: UM.Controller.properties.getValue("SpacingX") || base.spacingX }
    Binding { target: base; property: "spacingY"; value: UM.Controller.properties.getValue("SpacingY") || base.spacingY }

    Binding { target: rowsField;     property: "text"; value: base.rows;                 when: !rowsField.activeFocus }
    Binding { target: colsField;     property: "text"; value: base.cols;                 when: !colsField.activeFocus }
    Binding { target: spacingXField; property: "text"; value: base.spacingX.toFixed(2);  when: !spacingXField.activeFocus }
    Binding { target: spacingYField; property: "text"; value: base.spacingY.toFixed(2);  when: !spacingYField.activeFocus }
}
