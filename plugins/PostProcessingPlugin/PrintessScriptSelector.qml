// Copyright (c) 2024 Printess Technologies
// Script selector panel — sits next to the Slice button in the action bar.

import QtQuick 2.10
import QtQuick.Controls 2.3
import QtQuick.Layouts 1.3

import UM 1.5 as UM
import Cura 1.0 as Cura

Rectangle
{
    id: root

    // Widen the panel while the Layer-by-Layer warning is shown so it reads comfortably.
    width:  (warning.visible
                ? Math.max(scriptDropdown.width, Math.round(UM.Theme.getSize("combobox").width * 1.6))
                : scriptDropdown.width)
            + 2 * UM.Theme.getSize("default_margin").width
    height: header.height + body.height + warning.height

    // The action bar centers this panel on a fixed line, so any extra height
    // pushes the bottom edge down toward the Windows taskbar. Shift the panel
    // up by half the warning's height so the warning grows upward instead and
    // the bottom edge stays where it was before the warning appeared.
    transform: Translate { y: warning.visible ? -warning.height / 2 : 0 }

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

    // ── Layer-by-Layer warning ────────────────────────────────────────────────
    // Only shown when "Layer by Layer" (index 1) is the active script.
    Item
    {
        id: warning
        anchors { top: body.bottom; left: parent.left; right: parent.right }
        visible: scriptDropdown.currentIndex === 1
        height: visible ? warningRow.implicitHeight + 2 * UM.Theme.getSize("default_margin").height : 0
        clip: true

        RowLayout
        {
            id: warningRow
            anchors
            {
                left: parent.left
                right: parent.right
                verticalCenter: parent.verticalCenter
                leftMargin: UM.Theme.getSize("default_margin").width
                rightMargin: UM.Theme.getSize("default_margin").width
            }
            spacing: UM.Theme.getSize("narrow_margin").width

            UM.ColorImage
            {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: UM.Theme.getSize("section_icon").width
                Layout.preferredHeight: UM.Theme.getSize("section_icon").height
                source: UM.Theme.getIcon("Warning")
                color: UM.Theme.getColor("warning")
            }

            UM.Label
            {
                Layout.fillWidth: true
                text: "Do not use “Layer by Layer” when printing in well-plates. The dispense tip nozzle will interfere with the well-plate walls."
                font: UM.Theme.getFont("default")
                color: UM.Theme.getColor("text")
                wrapMode: Text.WordWrap
            }
        }
    }
}
