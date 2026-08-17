// Copyright (c) 2026 Printess Technologies
// Released under the terms of the LGPLv3 or higher.
//
// Opens the Path Designer from the action bar, beside the Well Plate Arranger,
// rather than only from the tool column down the left edge. Deliberately built
// to match WellPlateButton.qml: the two sit next to each other, so any drift in
// height, padding or colour reads as a mistake.

import QtQuick 2.10
import QtQuick.Controls 2.3
import UM 1.7 as UM
import Cura 1.7 as Cura

Item
{
    id: base

    implicitHeight: UM.Theme.getSize("button").height
    implicitWidth:  btnRow.implicitWidth + UM.Theme.getSize("default_margin").width * 2

    readonly property real halfGap: Math.round(UM.Theme.getSize("default_margin").width / 2)

    // Lit while the tool is open, so the button reads as a toggle rather than
    // leaving the drawing mode with nothing on screen to say it is on.
    //
    // Read off the panel URL rather than an active-tool id, because the QML
    // Controller does not expose one: ControllerProxy publishes setActiveTool as
    // a slot, and valid/activeToolPanel as properties, and nothing else. Both
    // notify on activeToolChanged, so this re-evaluates at the right moments.
    readonly property bool toolActive: UM.Controller.valid
        && String(UM.Controller.activeToolPanel).indexOf("PathDesignerPanel.qml") !== -1

    Rectangle
    {
        anchors.fill: parent
        radius: UM.Theme.getSize("default_radius").width
        color: base.toolActive || hoverArea.containsMouse
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
                source: Qt.resolvedUrl("PathDesigner.svg")
                width:  UM.Theme.getSize("button_icon").width
                height: UM.Theme.getSize("button_icon").height
                color:  UM.Theme.getColor("primary_button_text")
            }

            UM.Label
            {
                renderType: Text.QtRendering
                anchors.verticalCenter: parent.verticalCenter
                text: "Draw Paths"
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
            // Toggles. Closing goes through requestExit rather than clearing the
            // active tool, because the Path Designer asks what to do with
            // anything drawn since it was opened: closing changes nothing on the
            // build plate, since work is only printed once it is saved there.
            // Setting no tool directly would throw that prompt away, and with it
            // the drawing. The tool closes itself when there is nothing to ask.
            onClicked:
            {
                // Take focus first, exactly as the tool column does. Key events
                // only reach a tool when QML has not already accepted them:
                // MainWindow.keyPressEvent forwards to the key device solely if
                // the event comes back unaccepted. Leaving focus on whatever was
                // last clicked meant that item swallowed Escape, so Esc stopped
                // ending the line being drawn. It also commits any half-edited
                // setting field, which is why the stock toolbar does it too.
                forceActiveFocus()
                if (base.toolActive)
                {
                    UM.Controller.triggerAction("requestExit")
                }
                else
                {
                    UM.Controller.setActiveTool("PrintessPathDesigner")
                }
            }
        }
    }
}
