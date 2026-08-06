// Copyright (c) 2026 Printess Technologies
// Released under the terms of the LGPLv3 or higher.
//
// Tool panel for the Path Designer tool.

// QtQuick 2.15 is required: padding properties on Row/Text (used below) do not
// exist in the 2.2-era API and abort panel creation with older imports.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Window 2.15
import UM 1.7 as UM
import Cura 1.7 as Cura

Item
{
    id: base
    width: scroller.width
    height: scroller.height

    // Cap the panel so its bottom edge always stays inside the window; the
    // content scrolls inside instead. The cap is measured from where the panel
    // actually sits (the toolbar anchors it vertically), because a fixed
    // fraction of the window height overflows on short screens.
    property real maxPanelHeight: 420

    function recalcMaxHeight()
    {
        if (Window.height <= 0)
        {
            return
        }
        var top = 0
        if (parent)
        {
            var mapped = parent.mapToItem(null, 0, 0)
            if (mapped)
            {
                top = mapped.y
            }
        }
        // Leave a margin below so the last row clears the window edge.
        base.maxPanelHeight = Math.max(240, Window.height - top - 32)
    }

    Component.onCompleted: recalcMaxHeight()

    // The toolbar positions this panel after creation, so measure again once
    // the layout has settled.
    Timer { interval: 80; running: true; repeat: false; onTriggered: base.recalcMaxHeight() }

    Connections
    {
        target: Window.window
        ignoreUnknownSignals: true
        function onHeightChanged() { base.recalcMaxHeight() }
    }

    // -- State mirrored from Python ----------------------------------------
    property string shapeType: "line"
    property int    extruder: 0
    property int    pathLayers: 1
    property bool   snapEnabled: false
    property var    pathsInfo: []
    property int    selectedIndex: -1
    property int    pointCount: 0
    property var    extruderColors: ["#3f7ef0", "#f09a30"]
    property int    extruderCount: 2
    property string statusText: ""
    property string lineWidthText: "-"
    property string wellPreset: ""
    property var    wellInfo: []
    property int    wellCols: 0
    property string totalsText: ""
    property bool   canCopy: false
    property bool   canPaste: false

    // Bumped by Python when clicking the toolbar icon should ask what to do with
    // whatever has been drawn since the tool was opened. A counter rather than a
    // flag, so asking twice in a row still registers as two separate asks.
    property int    exitPrompt: 0
    onExitPromptChanged:
    {
        if (exitPrompt > 0)
        {
            exitDialog.open()
        }
    }

    readonly property int  panelWidth: 240
    readonly property real halfMargin: Math.round(UM.Theme.getSize("default_margin").width / 2)
    readonly property real sectionSpacing: UM.Theme.getSize("default_margin").height
    readonly property real controlHeight: UM.Theme.getSize("setting_control").height

    Flickable
    {
        id: scroller
        width: base.panelWidth + 12  // room for the scrollbar
        height: Math.min(contentCol.height, base.maxPanelHeight)
        contentWidth: base.panelWidth
        contentHeight: contentCol.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar
        {
            policy: contentCol.height > scroller.height ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
        }

    Column
    {
        id: contentCol
        width: base.panelWidth
        spacing: base.halfMargin

        // -- Shape ---------------------------------------------------------
        UM.Label { text: "Tool"; font: UM.Theme.getFont("default_bold") }

        Grid
        {
            columns: 3
            columnSpacing: base.halfMargin
            rowSpacing: base.halfMargin
            Repeater
            {
                model: [ { label: "Select",    value: "select" },
                         { label: "Line",      value: "line"   },
                         { label: "Arc",       value: "arc"    },
                         { label: "Circle",    value: "circle" },
                         { label: "Curve",     value: "spline" },
                         { label: "Rectangle", value: "rect"   },
                         { label: "Fill",      value: "fill"   },
                         { label: "Erase",     value: "erase"  } ]
                delegate: Button
                {
                    property bool sel: base.shapeType === modelData.value
                    implicitWidth: Math.floor((base.panelWidth - 2 * base.halfMargin) / 3)
                    implicitHeight: base.controlHeight
                    contentItem: Text
                    {
                        text: modelData.label
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font: UM.Theme.getFont("default")
                        color: sel ? UM.Theme.getColor("primary_button_text") : UM.Theme.getColor("text")
                    }
                    background: Rectangle
                    {
                        radius: UM.Theme.getSize("default_radius").width
                        color: sel ? UM.Theme.getColor("primary_button")
                                   : (parent.hovered ? UM.Theme.getColor("primary_button_hover")
                                                     : UM.Theme.getColor("main_background"))
                        border.color: sel ? UM.Theme.getColor("primary_button") : UM.Theme.getColor("lining")
                        border.width: UM.Theme.getSize("default_lining").width
                    }
                    onClicked: UM.Controller.setProperty("ShapeType", modelData.value)
                }
            }
        }

        // -- Extruder ------------------------------------------------------
        UM.Label
        {
            text: base.selectedIndex >= 0 ? "Extruder (selection)" : "Extruder"
            font: UM.Theme.getFont("default_bold")
            topPadding: base.halfMargin
        }

        Row
        {
            spacing: base.halfMargin
            Repeater
            {
                model: base.extruderCount > 1 ? [0, 1] : [0]
                delegate: Button
                {
                    property bool sel: base.extruder === modelData
                    implicitWidth: Math.floor((base.panelWidth - base.halfMargin) / 2)
                    implicitHeight: base.controlHeight
                    contentItem: Row
                    {
                        spacing: 6
                        leftPadding: 8
                        Rectangle
                        {
                            width: 10; height: 10; radius: 5
                            anchors.verticalCenter: parent.verticalCenter
                            color: base.extruderColors[modelData] !== undefined ? base.extruderColors[modelData] : "#888888"
                            border.color: UM.Theme.getColor("lining")
                            border.width: 1
                        }
                        Text
                        {
                            text: "Extruder " + (modelData + 1)
                            font: UM.Theme.getFont("default")
                            color: sel ? UM.Theme.getColor("primary_button_text") : UM.Theme.getColor("text")
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    background: Rectangle
                    {
                        radius: UM.Theme.getSize("default_radius").width
                        color: sel ? UM.Theme.getColor("primary_button")
                                   : (parent.hovered ? UM.Theme.getColor("primary_button_hover")
                                                     : UM.Theme.getColor("main_background"))
                        border.color: sel ? UM.Theme.getColor("primary_button") : UM.Theme.getColor("lining")
                        border.width: UM.Theme.getSize("default_lining").width
                    }
                    onClicked: UM.Controller.setProperty("Extruder", modelData)
                }
            }
        }

        // -- Path settings -------------------------------------------------
        UM.Label
        {
            text: base.selectedIndex >= 0 ? "Path Settings (selection)" : "Path Settings"
            font: UM.Theme.getFont("default_bold")
            topPadding: base.halfMargin
        }

        Grid
        {
            columns: 2
            columnSpacing: base.sectionSpacing
            rowSpacing: Math.round(base.halfMargin / 2)

            UM.Label { text: "Layers"; height: base.controlHeight; verticalAlignment: Text.AlignVCenter }
            UM.TextFieldWithUnit
            {
                id: layersField
                width: 104; height: base.controlHeight
                unit: ""
                validator: IntValidator { bottom: 1; top: 9999 }
                onEditingFinished:
                {
                    var v = parseInt(text)
                    if (!isNaN(v) && v >= 1) UM.Controller.setProperty("PathLayers", v)
                }
            }

            // Read-only: comes from the dispense tip profile, not editable here.
            UM.Label { text: "Line width"; height: base.controlHeight; verticalAlignment: Text.AlignVCenter }
            UM.Label
            {
                width: 104; height: base.controlHeight
                verticalAlignment: Text.AlignVCenter
                text: base.lineWidthText
                color: UM.Theme.getColor("text_detail")
            }
        }

        UM.Label
        {
            text: "The drawing is printed this many layers tall; each layer's height, "
                + "the line width, speed, flow, and fill density all come from your print settings."
            font: UM.Theme.getFont("small")
            color: UM.Theme.getColor("text_detail")
            width: parent.width
            wrapMode: Text.WordWrap
        }

        UM.CheckBox
        {
            id: snapCheck
            text: "Snap to line width (" + base.lineWidthText + ")"
            height: base.controlHeight
            onClicked: UM.Controller.setProperty("SnapEnabled", checked)
        }

        // -- Drawing actions -----------------------------------------------
        Row
        {
            spacing: base.halfMargin
            topPadding: base.halfMargin
            Cura.SecondaryButton
            {
                text: "Finish"
                height: base.controlHeight
                enabled: base.pointCount >= 2
                onClicked: UM.Controller.triggerAction("finishPath")
            }
        }

        // -- Well plate replication ----------------------------------------
        UM.Label
        {
            text: "Well Plate"
            font: UM.Theme.getFont("default_bold")
            topPadding: base.halfMargin
        }

        Row
        {
            spacing: base.halfMargin
            Repeater
            {
                model: [ { label: "None", value: ""        },
                         { label: "6",    value: "6-Well"  },
                         { label: "12",   value: "12-Well" },
                         { label: "24",   value: "24-Well" },
                         { label: "48",   value: "48-Well" } ]
                delegate: Button
                {
                    property bool sel: base.wellPreset === modelData.value
                    implicitWidth: Math.floor((base.panelWidth - 4 * base.halfMargin) / 5)
                    implicitHeight: base.controlHeight
                    contentItem: Text
                    {
                        text: modelData.label
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font: UM.Theme.getFont("default")
                        color: sel ? UM.Theme.getColor("primary_button_text") : UM.Theme.getColor("text")
                    }
                    background: Rectangle
                    {
                        radius: UM.Theme.getSize("default_radius").width
                        color: sel ? UM.Theme.getColor("primary_button")
                                   : (parent.hovered ? UM.Theme.getColor("primary_button_hover")
                                                     : UM.Theme.getColor("main_background"))
                        border.color: sel ? UM.Theme.getColor("primary_button") : UM.Theme.getColor("lining")
                        border.width: UM.Theme.getSize("default_lining").width
                    }
                    onClicked: UM.Controller.setProperty("WellPreset", modelData.value)
                }
            }
        }

        Grid
        {
            visible: base.wellCols > 0
            columns: Math.max(base.wellCols, 1)
            columnSpacing: 3
            rowSpacing: 3
            property int cell: Math.min(20, Math.floor((base.panelWidth - (base.wellCols - 1) * 3) / Math.max(base.wellCols, 1)))
            Repeater
            {
                model: base.wellInfo
                delegate: Rectangle
                {
                    width: parent.cell
                    height: parent.cell
                    radius: width / 2
                    color: modelData.source ? "#4caf50"
                         : (modelData.selected ? UM.Theme.getColor("primary_button")
                                               : UM.Theme.getColor("main_background"))
                    border.color: UM.Theme.getColor("lining")
                    border.width: 1

                    Text
                    {
                        anchors.centerIn: parent
                        visible: modelData.source
                        text: "S"
                        font.pixelSize: parent.width * 0.55
                        font.bold: true
                        color: "white"
                    }

                    MouseArea
                    {
                        anchors.fill: parent
                        onClicked: UM.Controller.triggerActionWithData("toggleWell", modelData.index)
                    }
                }
            }
        }

        Row
        {
            visible: base.wellCols > 0
            spacing: base.halfMargin
            Cura.SecondaryButton
            {
                text: "All Wells"
                height: base.controlHeight
                onClicked: UM.Controller.triggerAction("selectAllWells")
            }
            Cura.SecondaryButton
            {
                text: "None"
                height: base.controlHeight
                onClicked: UM.Controller.triggerAction("clearWellSelection")
            }
        }

        UM.Label
        {
            visible: base.wellCols > 0
            text: "Green S = the well you drew in (always printed). Click wells to give them a copy (blue)."
            font: UM.Theme.getFont("small")
            color: UM.Theme.getColor("text_detail")
            width: parent.width
            wrapMode: Text.WordWrap
        }

        // -- Path list -----------------------------------------------------
        UM.Label
        {
            text: "Paths (" + base.pathsInfo.length + ")"
            font: UM.Theme.getFont("default_bold")
            topPadding: base.halfMargin
            visible: base.pathsInfo.length > 0
        }

        Flickable
        {
            width: parent.width
            height: Math.min(listCol.height, 110)
            contentHeight: listCol.height
            clip: true
            visible: base.pathsInfo.length > 0

            Column
            {
                id: listCol
                width: parent.width
                Repeater
                {
                    model: base.pathsInfo
                    delegate: Rectangle
                    {
                        width: listCol.width
                        height: base.controlHeight
                        color: modelData.selected
                               ? UM.Theme.getColor("secondary")
                               : "transparent"
                        radius: UM.Theme.getSize("default_radius").width

                        Row
                        {
                            spacing: 6
                            leftPadding: 4
                            anchors.verticalCenter: parent.verticalCenter
                            Rectangle
                            {
                                width: 10; height: 10; radius: 5
                                anchors.verticalCenter: parent.verticalCenter
                                color: modelData.color
                                border.color: UM.Theme.getColor("lining")
                                border.width: 1
                            }
                            UM.Label { text: (modelData.index + 1) + ". " + modelData.label }
                        }

                        MouseArea
                        {
                            anchors.fill: parent
                            onClicked:
                            {
                                if (mouse.modifiers & Qt.ShiftModifier)
                                {
                                    UM.Controller.triggerActionWithData("toggleSelection", modelData.index)
                                }
                                else
                                {
                                    UM.Controller.setProperty("SelectedIndex",
                                        modelData.selected ? -1 : modelData.index)
                                }
                            }
                        }
                    }
                }
            }
        }

        Row
        {
            spacing: base.halfMargin
            visible: base.pathsInfo.length > 0
            Cura.SecondaryButton
            {
                text: "Select All"
                height: base.controlHeight
                onClicked: UM.Controller.triggerAction("selectAllPaths")
            }
            Cura.SecondaryButton
            {
                text: "Delete"
                height: base.controlHeight
                enabled: base.selectedIndex >= 0
                onClicked: UM.Controller.triggerAction("deleteSelected")
            }
            Cura.SecondaryButton
            {
                text: "Clear All"
                height: base.controlHeight
                onClicked: UM.Controller.triggerAction("clearAll")
            }
        }

        // Clipboard actions on their own row: six buttons will not fit across
        // the panel, and these mirror Ctrl+X / Ctrl+C / Ctrl+V.
        Row
        {
            spacing: base.halfMargin
            visible: base.pathsInfo.length > 0 || base.canPaste
            Cura.SecondaryButton
            {
                text: "Cut"
                height: base.controlHeight
                enabled: base.canCopy
                onClicked: UM.Controller.triggerAction("cutSelection")
            }
            Cura.SecondaryButton
            {
                text: "Copy"
                height: base.controlHeight
                enabled: base.canCopy
                onClicked: UM.Controller.triggerAction("copySelection")
            }
            Cura.SecondaryButton
            {
                text: "Paste"
                height: base.controlHeight
                enabled: base.canPaste
                onClicked: UM.Controller.triggerAction("pasteClipboard")
            }
        }

        // -- Totals readout ------------------------------------------------
        UM.Label
        {
            visible: base.totalsText !== ""
            text: base.totalsText
            font: UM.Theme.getFont("default_bold")
            width: parent.width
            wrapMode: Text.WordWrap
        }

        // -- Export --------------------------------------------------------
        Item
        {
            width: parent.width
            height: exportBtn.height + base.halfMargin
            Cura.PrimaryButton
            {
                id: exportBtn
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                width: parent.width
                text: "Save to Build Plate"
                enabled: base.pathsInfo.length > 0 || base.pointCount >= 2
                onClicked: UM.Controller.triggerAction("addToBuildPlate")
            }
        }

        // -- Status / hints ------------------------------------------------
        UM.Label
        {
            text: base.statusText
            width: parent.width
            wrapMode: Text.WordWrap
            color: UM.Theme.getColor("text_detail")
        }

        UM.Label
        {
            text: "Right-drag rotates the view."
            font: UM.Theme.getFont("small")
            color: UM.Theme.getColor("text_detail")
            width: parent.width
            wrapMode: Text.WordWrap
        }

        Row
        {
            spacing: base.halfMargin
            Cura.SecondaryButton
            {
                text: "Top View"
                height: base.controlHeight
                onClicked: UM.Controller.triggerAction("topView")
            }
        }

        // bottom breathing room so the last row isn't flush with the border
        Item { width: 1; height: base.halfMargin }
    }
    }  // Flickable

    // -- Bindings: Python to QML --------------------------------------------
    Binding { target: base; property: "shapeType";     value: UM.Controller.properties.getValue("ShapeType")     || "line" }
    Binding { target: base; property: "extruder";      value: UM.Controller.properties.getValue("Extruder")      || 0 }
    Binding { target: base; property: "pathLayers";    value: UM.Controller.properties.getValue("PathLayers")    || 1 }
    Binding { target: base; property: "snapEnabled";   value: UM.Controller.properties.getValue("SnapEnabled")   === true }
    Binding { target: base; property: "pathsInfo";     value: UM.Controller.properties.getValue("PathsInfo")     || [] }
    Binding { target: base; property: "pointCount";    value: UM.Controller.properties.getValue("PointCount")    || 0 }
    Binding { target: base; property: "statusText";    value: UM.Controller.properties.getValue("StatusText")    || "" }
    Binding { target: base; property: "extruderColors"; value: UM.Controller.properties.getValue("ExtruderColors") || ["#3f7ef0", "#f09a30"] }
    Binding { target: base; property: "extruderCount"; value: UM.Controller.properties.getValue("ExtruderCount") || 2 }
    Binding { target: base; property: "lineWidthText"; value: UM.Controller.properties.getValue("LineWidthText") || "-" }
    Binding { target: base; property: "wellPreset";    value: UM.Controller.properties.getValue("WellPreset")    || "" }
    Binding { target: base; property: "wellInfo";      value: UM.Controller.properties.getValue("WellInfo")      || [] }
    Binding { target: base; property: "wellCols";      value: UM.Controller.properties.getValue("WellCols")      || 0 }
    Binding { target: base; property: "totalsText";    value: UM.Controller.properties.getValue("TotalsText")    || "" }
    Binding { target: base; property: "canCopy";       value: UM.Controller.properties.getValue("CanCopy")       === true }
    Binding { target: base; property: "canPaste";      value: UM.Controller.properties.getValue("CanPaste")      === true }
    Binding { target: base; property: "exitPrompt";    value: UM.Controller.properties.getValue("ExitPrompt")    || 0 }
    Binding
    {
        target: base; property: "selectedIndex"
        value:
        {
            var v = UM.Controller.properties.getValue("SelectedIndex")
            return v === undefined ? -1 : v
        }
    }

    Binding { target: layersField;  property: "text"; value: base.pathLayers;    when: !layersField.activeFocus }
    Binding { target: snapCheck;    property: "checked"; value: base.snapEnabled }

    // -- Leaving the tool with unsaved work ---------------------------------
    // Closing Path Designer has never lost the drawing, but it does not put
    // anything on the build plate either: what has been drawn is not printed
    // until it is saved there. This is the moment to say so.
    //
    // Plain strings and UM.Label on purpose, to match the rest of this file. An
    // unresolved name (a catalog that was never declared, a theme size this Cura
    // does not have) aborts the whole component, and the panel then simply never
    // appears, with one line in cura.log to say why.
    UM.Dialog
    {
        id: exitDialog
        title: "Path Designer"
        width: 400
        height: 180
        minimumWidth: 400
        minimumHeight: 180

        UM.Label
        {
            anchors.fill: parent
            wrapMode: Text.WordWrap
            text: "You have changes that are not on the build plate yet.

"
                + "Save them so they print, or revert the drawing to how it was "
                + "when you opened Path Designer."
        }

        rightButtons:
        [
            Cura.SecondaryButton
            {
                text: "Cancel"
                onClicked: exitDialog.close()
            },
            Cura.SecondaryButton
            {
                text: "Revert changes"
                onClicked:
                {
                    exitDialog.close()
                    UM.Controller.triggerAction("discardSession")
                    UM.Controller.triggerAction("exitTool")
                }
            },
            Cura.PrimaryButton
            {
                text: "Save to build plate"
                // addToBuildPlate leaves the tool itself once it has saved.
                onClicked:
                {
                    exitDialog.close()
                    UM.Controller.triggerAction("addToBuildPlate")
                }
            }
        ]
    }

}
