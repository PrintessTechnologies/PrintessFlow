// Copyright (c) 2024 Printess Technologies
// Script selector panel — sits next to the Slice button in the action bar.

import QtQuick 2.10
import QtQuick.Controls 2.3

import UM 1.5 as UM
import Cura 1.0 as Cura

Rectangle
{
    id: root

    width:  scriptDropdown.width + 2 * UM.Theme.getSize("default_margin").width
    height: header.height + body.height

    color:        UM.Theme.getColor("main_background")
    border.width: UM.Theme.getSize("default_lining").width
    border.color: UM.Theme.getColor("lining")
    radius:       UM.Theme.getSize("default_radius").width
    clip:         true

    // ── Blue header ───────────────────────────────────────────────────────────
    Rectangle
    {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: titleLabel.implicitHeight + 2 * UM.Theme.getSize("default_margin").height
        color: UM.Theme.getColor("primary_button")

        UM.Label
        {
            id: titleLabel
            anchors.centerIn: parent
            width: parent.width - 2 * UM.Theme.getSize("default_margin").width
            horizontalAlignment: Text.AlignHCenter
            text: "Printess G-Code Formation Scripts"
            font: UM.Theme.getFont("default")
            color: UM.Theme.getColor("primary_button_text")
            elide: Text.ElideRight
        }
    }

    // ── Dropdown body ─────────────────────────────────────────────────────────
    Item
    {
        id: body
        anchors { top: header.bottom; left: parent.left; right: parent.right }
        height: scriptDropdown.height + 2 * UM.Theme.getSize("default_margin").height

        Cura.ComboBox
        {
            id: scriptDropdown
            anchors.centerIn: parent
            width: UM.Theme.getSize("combobox").width

            // Center the selected text inside the dropdown
            contentItem: UM.Label
            {
                anchors.fill: parent
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                text: scriptDropdown.currentText
                font: UM.Theme.getFont("default")
                color: UM.Theme.getColor("setting_control_text")
                elide: Text.ElideRight
            }

            model: ListModel
            {
                id: scriptModel
                ListElement { text: "None";                  scriptKey: "None" }
                ListElement { text: "Layer by Layer";        scriptKey: "PrintessLayerByLayer" }
                ListElement { text: "One Object at a Time";  scriptKey: "PrintessOneAtATime" }
            }
            textRole: "text"
            currentIndex: 0

            Component.onCompleted: updateIndex()

            Connections
            {
                target: manager
                function onScriptListChanged() { scriptDropdown.updateIndex() }
            }

            function updateIndex()
            {
                var active = manager.printessActiveScript
                if (active === "PrintessLayerByLayer") { currentIndex = 1; return }
                if (active === "PrintessOneAtATime")   { currentIndex = 2; return }
                currentIndex = 0
            }

            onActivated: manager.setPrintessActiveScript(scriptModel.get(currentIndex).scriptKey)
        }
    }
}
