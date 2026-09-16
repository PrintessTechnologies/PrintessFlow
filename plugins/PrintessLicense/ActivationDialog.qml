// Copyright (c) 2026 Printess Technologies
// Released under the terms of the LGPLv3 or higher.
//
// The activation dialog. Opened by the plugin at startup when there is no
// license (manager.gating is true: closing it quits the app), and from the
// Extensions > License menu at any time (gating false: closing just closes).
//
// QtQuick 2.15 and renderType: Text.QtRendering on every label, for the
// reasons written up in FlowTesterDialog.qml: the 2.2-era API lacks padding
// properties, and native (ClearType) rendering fringes glyphs on Windows.

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Window 2.15
import QtQuick.Dialogs

import UM 1.7 as UM
import Cura 1.7 as Cura

UM.Dialog
{
    id: dialog

    title: "Activate PrintessFlow"
    width: Math.round(520 * screenScaleFactor)
    height: Math.round(400 * screenScaleFactor)
    minimumWidth: Math.round(440 * screenScaleFactor)
    minimumHeight: Math.round(340 * screenScaleFactor)
    backgroundColor: UM.Theme.getColor("main_background")
    closeOnAccept: false

    readonly property int margin: Math.round(UM.Theme.getSize("default_margin").width)
    readonly property int halfMargin: Math.round(UM.Theme.getSize("default_margin").width / 2)
    readonly property int lining: Math.round(UM.Theme.getSize("default_lining").width)
    readonly property int buttonHeight: Math.round(UM.Theme.getSize("action_button").height)

    function tryActivate()
    {
        var problem = manager.activate(codeField.text)
        errorLabel.text = problem
        if (problem === "")
        {
            codeField.text = ""
            dialog.visible = false
        }
    }

    // The code field takes focus whenever the dialog opens, so a paste works
    // straight away; nothing else in the dialog wants the keyboard. Deferred
    // through a timer: UM.Dialog's own ColumnLayout binds `focus: base.visible`,
    // and that binding lands after this handler and takes the focus back if
    // the field claims it synchronously.
    onVisibleChanged:
    {
        if (visible)
        {
            errorLabel.text = ""
            focusTimer.start()
        }
    }

    // Return activates; the window close button and Escape go through reject.
    onAccepted: tryActivate()
    onRejected:
    {
        if (manager.gating)
        {
            manager.quitApplication()
        }
    }

    Column
    {
        anchors.fill: parent
        spacing: dialog.margin

        UM.Label
        {
            renderType: Text.QtRendering
            width: parent.width
            text: manager.statusText
            color: UM.Theme.getColor("text")
            wrapMode: Text.WordWrap
        }

        UM.Label
        {
            renderType: Text.QtRendering
            width: parent.width
            text: "Activation code"
            font: UM.Theme.getFont("default_bold")
            color: UM.Theme.getColor("text")
        }

        // A TextArea rather than a TextField: the code is a long single line
        // and an emailed copy often arrives wrapped, so let it wrap here too
        // and show the whole thing. The plugin strips the whitespace.
        Rectangle
        {
            width: parent.width
            height: Math.round(90 * screenScaleFactor)
            color: UM.Theme.getColor("main_background")
            border.width: dialog.lining
            border.color: codeField.activeFocus ? UM.Theme.getColor("text_field_border_active")
                                               : UM.Theme.getColor("text_field_border")
            radius: UM.Theme.getSize("setting_control_radius").width

            ScrollView
            {
                anchors.fill: parent
                anchors.margins: dialog.lining
                clip: true

                TextArea
                {
                    id: codeField
                    renderType: Text.QtRendering
                    font: UM.Theme.getFont("default")
                    color: UM.Theme.getColor("text")
                    selectionColor: UM.Theme.getColor("text_selection")
                    selectedTextColor: UM.Theme.getColor("text")
                    placeholderText: "PF1-…"
                    placeholderTextColor: UM.Theme.getColor("text")
                    wrapMode: TextEdit.WrapAnywhere
                    background: Item {}
                    padding: dialog.halfMargin
                    // Return submits. Shift+Return still inserts a newline,
                    // which the plugin strips anyway.
                    Keys.onReturnPressed: (event) =>
                    {
                        if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return }
                        dialog.tryActivate()
                    }
                    Keys.onEnterPressed: (event) => dialog.tryActivate()
                    onTextChanged: errorLabel.text = ""
                }
            }
        }

        Row
        {
            spacing: dialog.halfMargin

            Cura.SecondaryButton
            {
                height: dialog.buttonHeight
                text: "Import license file..."
                onClicked: importDialog.open()
            }
        }

        UM.Label
        {
            id: errorLabel
            renderType: Text.QtRendering
            width: parent.width
            text: ""
            visible: text !== ""
            color: UM.Theme.getColor("error")
            wrapMode: Text.WordWrap
        }

        UM.Label
        {
            renderType: Text.QtRendering
            width: parent.width
            text: "Don't have a code? Email contact@printesstechnologies.com."
            font: UM.Theme.getFont("small")
            color: UM.Theme.getColor("text")
            wrapMode: Text.WordWrap
        }
    }

    leftButtons:
    [
        Cura.SecondaryButton
        {
            height: dialog.buttonHeight
            text: manager.gating ? "Quit PrintessFlow" : "Close"
            onClicked: dialog.reject()
        }
    ]

    rightButtons:
    [
        Cura.PrimaryButton
        {
            height: dialog.buttonHeight
            text: "Activate"
            enabled: codeField.text.trim() !== ""
            onClicked: dialog.tryActivate()
        }
    ]

    // Inside a holder Item: QtQuick.Dialogs.FileDialog and Timer are QtObjects
    // in Qt6, not Items, and UM.Dialog's contents is a list<Item>.
    Item
    {
        Timer
        {
            id: focusTimer
            interval: 50
            repeat: false
            onTriggered: codeField.forceActiveFocus()
        }

        FileDialog
        {
            id: importDialog
            title: "Import PrintessFlow License"
            fileMode: FileDialog.OpenFile
            nameFilters: ["PrintessFlow license (*.lic *.txt)", "All files (*)"]
            onAccepted:
            {
                var problem = manager.activateFromFile(selectedFile)
                errorLabel.text = problem
                if (problem === "")
                {
                    codeField.text = ""
                    dialog.visible = false
                }
            }
        }
    }
}
