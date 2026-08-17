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
        // One margin's worth, not two: the title font went up a size for
        // consistency with the buttons beside it, and the header would otherwise
        // grow back everything the note below just gave up.
        height: titleLabel.implicitHeight + UM.Theme.getSize("default_margin").height
        color: UM.Theme.getColor("primary_button")

        UM.Label
        {
            renderType: Text.QtRendering
            id: titleLabel
            anchors.centerIn: parent
            width: parent.width - 2 * UM.Theme.getSize("default_margin").width
            horizontalAlignment: Text.AlignHCenter
            text: "Printess G-Code Formation Scripts"
            // Same face as Draw Paths and Well Plate Arranger. These sit in one
            // row, so a different weight or size on any of them reads as an
            // accident rather than a distinction.
            font: UM.Theme.getFont("medium_bold")
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
                renderType: Text.QtRendering
                anchors.fill: parent
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                text: scriptDropdown.currentText
                font: UM.Theme.getFont("default")
                color: UM.Theme.getColor("setting_control_text")
                elide: Text.ElideRight
            }

            // One Object at a Time is the default (pre-activated by the machine
            // instance) and listed first; Layer by Layer must be picked explicitly.
            model: ListModel
            {
                id: scriptModel
                ListElement { text: "One Object at a Time";  scriptKey: "PrintessOneAtATime" }
                ListElement { text: "Layer by Layer";        scriptKey: "PrintessLayerByLayer" }
                ListElement { text: "None";                  scriptKey: "None" }
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
                if (active === "PrintessOneAtATime")   { currentIndex = 0; return }
                if (active === "PrintessLayerByLayer") { currentIndex = 1; return }
                currentIndex = 2
            }

            onActivated: manager.setPrintessActiveScript(scriptModel.get(currentIndex).scriptKey)
        }
    }

    // ── Guidance note ─────────────────────────────────────────────────────────
    // Model order: 0 = One Object at a Time, 1 = Layer by Layer, 2 = None.
    // Index 0 gets a recommendation note, index 1 the well-plate warning.
    Item
    {
        id: warning
        anchors { top: body.bottom; left: parent.left; right: parent.right }
        visible: scriptDropdown.currentIndex === 0 || scriptDropdown.currentIndex === 1
        // One margin's worth of padding, not two. The note is secondary text and
        // the panel sits in the action bar, where every extra millimetre of
        // height pushes the bottom edge toward the taskbar.
        height: visible ? warningRow.implicitHeight + UM.Theme.getSize("default_margin").height : 0
        clip: true

        readonly property bool isWarning: scriptDropdown.currentIndex === 1

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
                // Scaled with the note itself rather than left at section_icon,
                // which is sized for a heading and dwarfs small body text.
                Layout.preferredWidth: Math.round(UM.Theme.getSize("section_icon").width * 0.75)
                Layout.preferredHeight: Math.round(UM.Theme.getSize("section_icon").height * 0.75)
                source: warning.isWarning ? UM.Theme.getIcon("Warning") : UM.Theme.getIcon("Information")
                color: warning.isWarning ? UM.Theme.getColor("warning") : UM.Theme.getColor("primary_button")
            }

            UM.Label
            {
                renderType: Text.QtRendering
                Layout.fillWidth: true
                text: warning.isWarning
                    ? "Do not use “Layer by Layer” when printing in well-plates. The dispense tip nozzle will interfere with the well-plate walls."
                    : "Recommended for Standard Gel Printing. One object is completed before the next one begins."
                font: UM.Theme.getFont("small")
                color: UM.Theme.getColor("text")
                wrapMode: Text.WordWrap
            }
        }
    }
}
