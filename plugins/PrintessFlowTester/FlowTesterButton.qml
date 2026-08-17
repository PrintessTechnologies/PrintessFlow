// Copyright (c) 2026 Printess Technologies
// Released under the terms of the LGPLv3 or higher.
//
// Opens the Flow Rate Tester from the action bar, beside Draw Paths and the
// Well Plate Arranger. Deliberately built to match PathDesignerButton.qml: the
// three sit in one row, so any drift in height, padding or color reads as a
// mistake rather than as a distinction.
//
// Unlike Draw Paths this is not a toggle. There is no tool to be in: the button
// opens a dialog, so there is no "on" state to light, and lighting it while the
// dialog happened to be open would promise a toggle that the button does not
// implement.

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

    Rectangle
    {
        anchors.fill: parent
        radius: UM.Theme.getSize("default_radius").width
        color: hoverArea.containsMouse
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
                source: Qt.resolvedUrl("FlowTester.svg")
                width:  UM.Theme.getSize("button_icon").width
                height: UM.Theme.getSize("button_icon").height
                color:  UM.Theme.getColor("primary_button_text")
            }

            UM.Label
            {
                renderType: Text.QtRendering
                anchors.verticalCenter: parent.verticalCenter
                text: "Flow Test"
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
            onClicked:
            {
                // Take focus first, exactly as the tool column and the Draw
                // Paths button do. It commits any half-edited setting field, so
                // a flow typed into the print settings panel is already applied
                // by the time the dialog reads the profile.
                forceActiveFocus()
                manager.showDialog()
            }
        }
    }
}
