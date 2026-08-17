// Copyright (c) 2026 Printess Technologies
// Released under the terms of the LGPLv3 or higher.
//
// The Flow Rate Tester table.
//
// QtQuick 2.15 deliberately, matching PathDesignerPanel: padding properties on
// Row/Text do not exist in the 2.2-era API and an unresolved name aborts the
// whole component, after which the dialog simply never appears.

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Window 2.15
import QtQuick.Dialogs

import UM 1.7 as UM
import Cura 1.7 as Cura

UM.Dialog
{
    id: dialog

    title: "Flow Rate Tester"
    // Rounded, like every other size in here. screenScaleFactor is fractional at
    // any non-integer display scaling (1.25, 1.5), so an unrounded dialog width
    // makes the content Item fractional, and everything anchored inside it then
    // inherits a fractional origin. See the note on controlHeight below.
    width: Math.round(560 * screenScaleFactor)
    height: Math.round(620 * screenScaleFactor)
    minimumWidth: Math.round(460 * screenScaleFactor)
    minimumHeight: Math.round(420 * screenScaleFactor)
    backgroundColor: UM.Theme.getColor("main_background")

    property int extruderIndex: 0
    property var summary: ({})

    // Maintained by rowsModel.recompute() rather than bound to the model. A
    // binding that reads rowsModel.get(i) never re-evaluates: ListModel role
    // changes are not property changes, so the total would be right once and
    // then silently stale for the rest of the session.
    property real totalPlunger: 0

    // ALL int, never real, so nothing in this dialog is laid out on a half
    // pixel. `margin` is the one that matters most: it is not just a spacing
    // value, it is the topMargin and bottomMargin on the anchors of the header,
    // the controls row, the table frame and the footer, so a fractional margin
    // gives all four a fractional Y ORIGIN that every label inside inherits.
    // Rounding the leaf sizes cannot help while their containers start on a
    // half pixel.
    //
    // This is good hygiene but it was NOT the cause of the malformed letters -
    // see the renderType note on every UM.Label below. Keeping the two straight
    // matters, because rounding was tried first and did not fix anything.
    readonly property int margin: Math.round(UM.Theme.getSize("default_margin").width)
    readonly property int halfMargin: Math.round(UM.Theme.getSize("default_margin").width / 2)
    readonly property int lining: Math.round(UM.Theme.getSize("default_lining").width)
    readonly property int controlHeight: Math.round(UM.Theme.getSize("setting_control").height)
    readonly property int buttonHeight: Math.round(UM.Theme.getSize("action_button").height)

    // Every fixed pixel size below the dialog itself is scaled. The dialog was
    // (width/height above), its children were not, so at 150% display scaling
    // the fonts grew by half and the columns did not, leaving each column a
    // third narrower than the text written into it.
    readonly property int colLine:    Math.round(60 * screenScaleFactor)
    readonly property int colFlow:    Math.round(100 * screenScaleFactor)
    readonly property int colPlunger: Math.round(160 * screenScaleFactor)
    readonly property int colPosition: Math.round(100 * screenScaleFactor)

    // Every derived number in this dialog comes from the live profile, so it is
    // re-read whenever the dialog opens or the extruder changes rather than
    // captured once. Changing the dispense tip and reopening must be enough.
    function refresh()
    {
        dialog.summary = manager.summaryFor(dialog.extruderIndex)
        rowsModel.recompute()
        dialog.checkFit()
    }

    function checkFit()
    {
        var result = manager.checkFit(dialog.extruderIndex, rowsModel.count)
        fitWarning.text = result.ok ? "" : result.message
    }

    // A sweep of plus or minus 20% around wherever the user's Flow actually
    // sits. A fixed 80-120 is only useful for someone already near 100: at
    // Flow 200 on a thick paste every line in that sweep under-extrudes and the
    // whole strip is wasted. At Flow 100 this returns 80 and 120, so the
    // familiar default is unchanged for anyone on a stock profile.
    function defaultRange()
    {
        var f = (dialog.summary && dialog.summary.profileFlow > 0)
            ? dialog.summary.profileFlow : 100
        return [Math.max(1, Math.round(f * 0.8)), Math.round(f * 1.2)]
    }

    Component.onCompleted:
    {
        // The summary has to be read BEFORE the range is derived from it, so
        // this does not go through refresh(): that would fill the table from a
        // summary that is still empty and center the first sweep on 100
        // whatever the profile said.
        dialog.summary = manager.summaryFor(dialog.extruderIndex)
        var range = dialog.defaultRange()
        fromField.text = range[0]
        toField.text = range[1]
        rowsModel.fillRange(range[0], range[1], 5)
        dialog.checkFit()
    }

    // Everything non-visual hangs off this holder, NOT off the dialog directly.
    // UM.Dialog's default property is `contents`, which is a list of ITEMS, so
    // a bare QtObject child fails the whole component with
    //   "Cannot assign object to list property contents"
    // and the dialog then never appears at all. A zero-size Item is a legal
    // member of that list and can parent anything.
    Item
    {
        Connections
        {
            target: manager
            function onSettingsChanged() { dialog.refresh() }
        }

        ListModel
        {
            id: rowsModel

            // Replaces the whole table with `lines` values stepped evenly from
            // `from` to `to`. A single row is just `from`: dividing by lines - 1
            // would be a division by zero, and the honest answer for one line is
            // the value the user typed as the start.
            //
            // The parameter is `lines`, not `count`, so it cannot shadow the
            // model's own count property inside this function.
            function fillRange(from, to, lines)
            {
                clear()
                var n = Math.max(1, Math.round(lines))
                for (var i = 0; i < n; i++)
                {
                    var value = n === 1 ? from : from + (to - from) * i / (n - 1)
                    append({ "flow": Math.round(value * 10) / 10, "plunger": 0 })
                }
                recompute()
            }

            function setCount(n)
            {
                n = Math.max(1, Math.min(manager.maxLines, Math.round(n)))
                while (count > n) { remove(count - 1) }
                // A new row copies the last one rather than defaulting to 100:
                // rows are added to extend a sweep, and repeating the end of it
                // is a better starting point than jumping back to the middle.
                while (count < n) { append({ "flow": count > 0 ? get(count - 1).flow : 100, "plunger": 0 }) }
                recompute()
            }

            function recompute()
            {
                var total = 0
                for (var i = 0; i < count; i++)
                {
                    var mm = manager.plungerForFlow(dialog.extruderIndex, get(i).flow)
                    setProperty(i, "plunger", mm)
                    total += mm
                }
                dialog.totalPlunger = total
            }
        }
    }

    Item
    {
        anchors.fill: parent

        // ── Settings this test will use ───────────────────────────────────
        Column
        {
            id: header
            anchors { top: parent.top; left: parent.left; right: parent.right }
            spacing: dialog.halfMargin

            // renderType: Text.QtRendering appears on EVERY UM.Label in this
            // file. This is why:
            //
            // UM/Label.qml sets
            //     renderType: Qt.platform.os == "osx" ? QtRendering : NativeRendering
            // so on Windows every label is drawn with ClearType SUBPIXEL
            // antialiasing, which paints each glyph across the red, green and
            // blue stripes of a pixel. When the glyph does not land where the
            // rasterizer assumed, those stripes stop canceling and show as
            // color: the user's screenshot had individual letters tinted blue
            // and orange, which reads as "malformed letters".
            //
            // Rounding every position and size was tried first and did NOT fix
            // it (that work is kept, it is still correct). QtRendering switches
            // to grayscale antialiasing, which has no color channels to fringe
            // and does not care about subpixel placement. Slightly softer than
            // ClearType at small sizes; no fringing, which is the trade worth
            // making. macOS already uses it, so this only aligns Windows.
            UM.Label
            {
                renderType: Text.QtRendering
                width: parent.width
                // What the strip is and what to do with it. The scope note (which
                // flow is being set, and which are excluded) belongs to the
                // settings line below and is NOT repeated here: it was said
                // three times across these two paragraphs.
                text: "Each line is " + manager.lineLength.toFixed(0) + " mm long and "
                    + manager.lineGap.toFixed(0) + " mm apart, printed in a single layer "
                    + "centered on the build plate, with line 1 at the front.\n\n"
                    + "Print the strip, pick the line that looks best, and set Flow to that value."
                font: UM.Theme.getFont("default")
                color: UM.Theme.getColor("text")
                wrapMode: Text.WordWrap
            }

            Row
            {
                spacing: dialog.margin
                visible: manager.extruderCount > 1

                UM.Label
                {
                    renderType: Text.QtRendering
                    text: "Extruder"
                    height: dialog.controlHeight
                    verticalAlignment: Text.AlignVCenter
                }

                Cura.ComboBox
                {
                    id: extruderCombo
                    width: Math.round(160 * screenScaleFactor)
                    height: dialog.controlHeight
                    textRole: "text"
                    model: ListModel
                    {
                        id: extruderModel
                        Component.onCompleted:
                        {
                            for (var i = 0; i < manager.extruderCount; i++)
                            {
                                append({ "text": "Syringe " + (i + 1) })
                            }
                        }
                    }
                    currentIndex: dialog.extruderIndex
                    onActivated:
                    {
                        dialog.extruderIndex = currentIndex
                        dialog.refresh()
                    }
                }
            }

            // The profile values the extrusion is computed from. The table value
            // is the GENERAL Flow and the only flow applied: wall flow and
            // initial layer flow are both excluded, so there is no multiplier
            // left to warn about and nothing can shift what the labels mean.
            UM.Label
            {
                renderType: Text.QtRendering
                width: parent.width
                text:
                {
                    if (!dialog.summary || dialog.summary.lineWidth === undefined) return ""
                    var s = dialog.summary
                    return (s.tipName ? s.tipName : "Active profile")
                        + ": line width " + s.lineWidth.toFixed(2) + " mm"
                        + ", layer height " + s.layerHeight.toFixed(2) + " mm"
                        + ", speed " + s.speed.toFixed(1) + " mm/s"
                        + ", syringe " + s.materialDiameter.toFixed(2) + " mm"
                        + ", Flow " + s.profileFlow.toFixed(0) + "%."
                        + "  The table sets the normal Flow; wall flow and initial "
                        + "layer flow are not applied."
                }
                font: UM.Theme.getFont("small")
                // NOT text_detail. That theme color is 50% alpha in the light
                // theme (174,174,174,128 → about 214 gray once composited on
                // white, roughly 1.3:1 contrast) and no stock Cura QML outside
                // these plugins uses it for body text. Translucent text is also
                // what mangles the letterforms: NativeRendering antialiases a
                // partly transparent glyph badly, so strokes drop out unevenly.
                //
                // The secondary lines here are demoted by SIZE ("small") and
                // not by color. text_medium was the obvious substitute but
                // measures 3.95:1 on the light background and 4.17:1 on the
                // dark one, under the 4.5:1 that small text wants, and this
                // paragraph is where the flow numbers are explained.
                color: UM.Theme.getColor("text")
                wrapMode: Text.WordWrap
            }
        }

        // ── Line count and the fill-range helper ──────────────────────────
        Row
        {
            id: controls
            anchors { top: header.bottom; topMargin: dialog.margin; left: parent.left }
            spacing: dialog.halfMargin

            UM.Label { renderType: Text.QtRendering; text: "Lines"; height: dialog.controlHeight; verticalAlignment: Text.AlignVCenter }

            UM.TextFieldWithUnit
            {
                id: countField
                width: Math.round(56 * screenScaleFactor); height: dialog.controlHeight
                unit: ""
                text: rowsModel.count
                validator: IntValidator { bottom: 1; top: manager.maxLines }
                onEditingFinished:
                {
                    var v = parseInt(text)
                    if (!isNaN(v)) rowsModel.setCount(v)
                    text = rowsModel.count
                    dialog.checkFit()
                }
            }

            UM.Label
            {
                renderType: Text.QtRendering
                text: "   Fill from"
                height: dialog.controlHeight
                verticalAlignment: Text.AlignVCenter
            }

            UM.TextFieldWithUnit
            {
                id: fromField
                width: Math.round(72 * screenScaleFactor); height: dialog.controlHeight
                unit: "%"
                text: "80"
                validator: DoubleValidator { bottom: 1; top: 500; decimals: 1; notation: DoubleValidator.StandardNotation }
            }

            UM.Label { renderType: Text.QtRendering; text: "to"; height: dialog.controlHeight; verticalAlignment: Text.AlignVCenter }

            UM.TextFieldWithUnit
            {
                id: toField
                width: Math.round(72 * screenScaleFactor); height: dialog.controlHeight
                unit: "%"
                text: "120"
                validator: DoubleValidator { bottom: 1; top: 500; decimals: 1; notation: DoubleValidator.StandardNotation }
            }

            Cura.SecondaryButton
            {
                height: dialog.controlHeight
                text: "Apply"
                onClicked:
                {
                    var a = parseFloat(fromField.text)
                    var b = parseFloat(toField.text)
                    if (isNaN(a) || isNaN(b)) return
                    rowsModel.fillRange(a, b, rowsModel.count)
                    dialog.checkFit()
                }
            }
        }

        // ── The table ─────────────────────────────────────────────────────
        Row
        {
            id: tableHeader
            // Left only. A Row sizes itself from its children, so anchoring
            // both edges fights that; the columns below have fixed widths and
            // the header has to line up with them, not with the dialog.
            anchors { top: controls.bottom; topMargin: dialog.margin; left: parent.left }
            height: dialog.controlHeight

            // NoWrap on every fixed-width label in the table, header and rows
            // alike. UM.Label defaults to Text.Wrap, so a heading a few pixels
            // too wide for its column silently became two lines inside a
            // single-line row: what shows then is the top half of one line and
            // the bottom half of the next, which reads as broken letters rather
            // than as a layout problem. Eliding says the same thing honestly.
            UM.Label { renderType: Text.QtRendering; width: dialog.colLine; text: "Line"; font: UM.Theme.getFont("default_bold"); verticalAlignment: Text.AlignVCenter; height: parent.height; wrapMode: Text.NoWrap; elide: Text.ElideRight }
            // colFlow matches the flow field's width in the delegate below. Any
            // other number slides every column after it out of line with the
            // rows it heads.
            UM.Label { renderType: Text.QtRendering; width: dialog.colFlow; text: "Flow"; font: UM.Theme.getFont("default_bold"); verticalAlignment: Text.AlignVCenter; height: parent.height; wrapMode: Text.NoWrap; elide: Text.ElideRight }
            UM.Label { renderType: Text.QtRendering; width: dialog.colPlunger; text: "Plunger travel"; font: UM.Theme.getFont("default_bold"); verticalAlignment: Text.AlignVCenter; height: parent.height; wrapMode: Text.NoWrap; elide: Text.ElideRight }
            UM.Label { renderType: Text.QtRendering; width: dialog.colPosition; text: "Position"; font: UM.Theme.getFont("default_bold"); verticalAlignment: Text.AlignVCenter; height: parent.height; wrapMode: Text.NoWrap; elide: Text.ElideRight }
        }

        Rectangle
        {
            id: tableFrame
            anchors
            {
                top: tableHeader.bottom
                left: parent.left
                right: parent.right
                bottom: footer.top
                bottomMargin: dialog.margin
            }
            color: UM.Theme.getColor("main_background")
            border.width: dialog.lining
            border.color: UM.Theme.getColor("lining")
            clip: true

            ListView
            {
                id: rowsView
                anchors.fill: parent
                anchors.margins: dialog.lining
                model: rowsModel
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { }

                delegate: Row
                {
                    width: rowsView.width
                    // The padding is forced EVEN. The flow field inside is
                    // verticalCenter'd, so an odd difference between row and
                    // field height puts it half a pixel off, and half a pixel
                    // is exactly what native rendering cannot hint. At 125%
                    // scaling a plain round(4 * scale) is 5, and every row in
                    // the table would sit on the wrong grid.
                    height: dialog.controlHeight + 2 * Math.round(2 * screenScaleFactor)

                    UM.Label
                    {
                        renderType: Text.QtRendering
                        width: dialog.colLine; height: parent.height
                        text: (index + 1)
                        verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.NoWrap
                    }

                    UM.TextFieldWithUnit
                    {
                        width: dialog.colFlow; height: dialog.controlHeight
                        anchors.verticalCenter: parent.verticalCenter
                        unit: "%"
                        text: model.flow
                        validator: DoubleValidator { bottom: 1; top: 500; decimals: 1; notation: DoubleValidator.StandardNotation }
                        onEditingFinished:
                        {
                            var v = parseFloat(text)
                            // Reject rather than clamp, and put the old value
                            // back: silently substituting a number the user did
                            // not type is how a test strip ends up labeled
                            // with a flow it was not printed at.
                            //
                            // Restored as a BINDING, not as a plain assignment.
                            // A bare `text = model.flow` breaks the binding for
                            // good, and this cell would then ignore every later
                            // Apply while the model underneath it moved on.
                            if (isNaN(v) || v <= 0)
                            {
                                text = Qt.binding(function() { return model.flow })
                                return
                            }
                            rowsModel.setProperty(index, "flow", v)
                            // Through recompute() rather than setting this row's
                            // plunger directly, so the running total at the
                            // bottom is recalculated too. Setting the one cell
                            // left the total showing the sum from before the
                            // edit.
                            rowsModel.recompute()
                        }
                    }

                    UM.Label
                    {
                        renderType: Text.QtRendering
                        width: dialog.colPlunger; height: parent.height
                        // Full-strength text. This is a number the user reads
                        // off to decide whether the strip fits in the syringe,
                        // not a decoration, and it sat in the same washed-out
                        // gray as the notes.
                        color: UM.Theme.getColor("text")
                        text: model.plunger.toFixed(4) + " mm"
                        verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.NoWrap
                        elide: Text.ElideRight
                    }

                    UM.Label
                    {
                        renderType: Text.QtRendering
                        width: dialog.colPosition; height: parent.height
                        text: index === 0 ? "front" : (index === rowsModel.count - 1 ? "back" : "")
                        color: UM.Theme.getColor("text")
                        verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.NoWrap
                        elide: Text.ElideRight
                    }
                }
            }
        }

        // ── Warning and actions ───────────────────────────────────────────
        Column
        {
            id: footer
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
            spacing: dialog.halfMargin

            Row
            {
                width: parent.width
                spacing: dialog.halfMargin
                visible: fitWarning.text !== ""

                UM.ColorImage
                {
                    id: fitWarningIcon
                    width: Math.round(UM.Theme.getSize("section_icon").width * 0.75)
                    height: Math.round(UM.Theme.getSize("section_icon").height * 0.75)
                    source: UM.Theme.getIcon("Warning")
                    color: UM.Theme.getColor("warning")
                }

                UM.Label
                {
                    renderType: Text.QtRendering
                    id: fitWarning
                    // Measured off the icon that is actually there plus the gap,
                    // not off the full-size section_icon. Subtracting the wrong
                    // width left the wrapped text a few pixels wider than the
                    // row, so the last word ran under the dialog edge.
                    width: parent.width - fitWarningIcon.width - parent.spacing
                    text: ""
                    font: UM.Theme.getFont("small")
                    color: UM.Theme.getColor("text")
                    wrapMode: Text.WordWrap
                }
            }

            // What the whole strip costs in plunger travel. A syringe has a
            // finite stroke, and a wide sweep over many lines can quietly ask
            // for more of it than is left; the number is cheap to show and
            // expensive to discover halfway through a print.
            UM.Label
            {
                renderType: Text.QtRendering
                width: parent.width
                text: "Total plunger travel: " + dialog.totalPlunger.toFixed(2) + " mm over "
                    + rowsModel.count + (rowsModel.count === 1 ? " line." : " lines.")
                font: UM.Theme.getFont("small")
                color: UM.Theme.getColor("text")
                wrapMode: Text.WordWrap
            }

            Row
            {
                anchors.right: parent.right
                spacing: dialog.halfMargin

                Cura.SecondaryButton
                {
                    height: dialog.buttonHeight
                    text: "Close"
                    onClicked: dialog.close()
                }

                Cura.PrimaryButton
                {
                    height: dialog.buttonHeight
                    text: "Save G-Code"
                    // Disabled rather than allowed-then-refused: the strip not
                    // fitting is known before the button is pressed, so saying
                    // so up front beats a file dialog that ends in an error.
                    enabled: fitWarning.text === "" && rowsModel.count > 0
                    onClicked: saveDialog.open()
                }
            }
        }
    }

    // Also inside a holder Item, and for the same reason as the ListModel:
    // QtQuick.Dialogs.FileDialog is a QtObject in Qt6, not an Item, so as a
    // direct child of UM.Dialog it fails `contents` (a list<Item>) too. An
    // Item's own default property accepts any QtObject, so this is safe here.
    Item
    {
        FileDialog
        {
            id: saveDialog
            title: "Save Flow Test G-Code"
            fileMode: FileDialog.SaveFile
            nameFilters: ["G-code files (*.gcode)"]
            defaultSuffix: "gcode"
            // The folder Cura last saved g-code to, registered by
            // LocalFileOutputDevicePlugin. Naming a key that nothing registers
            // would make getDefaultPath compare None against the filesystem and
            // throw, taking the dialog with it.
            currentFolder: CuraApplication.getDefaultPath("dialog_save_path")
            onAccepted:
            {
                var flows = []
                for (var i = 0; i < rowsModel.count; i++) { flows.push(rowsModel.get(i).flow) }
                if (manager.saveGcode(selectedFile, dialog.extruderIndex, flows))
                {
                    dialog.close()
                }
            }
        }
    }
}
