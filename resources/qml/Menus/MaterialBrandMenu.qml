// Copyright (c) 2022 UltiMaker
// Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.7
import QtQuick.Controls 2.4
import QtQuick.Layouts 2.7

import UM 1.5 as UM
import Cura 1.7 as Cura

/* This element is a workaround for MacOS, where it can crash in Qt6 when nested menus are closed.
Instead we'll use a pop-up which doesn't seem to have that problem. */

Cura.MenuItem
{
    id: materialBrandMenu
    height: UM.Theme.getSize("menu").height + UM.Theme.getSize("narrow_margin").height
    overrideShowArrow: true

    property var materialTypesModel
    text: materialTypesModel.name

    contentItem: MouseArea
    {
        hoverEnabled: true

        RowLayout
        {
            spacing: 0
            opacity: materialBrandMenu.enabled ? 1 : 0.5

            Item
            {
                // Spacer
                width: UM.Theme.getSize("default_margin").width
            }

            UM.Label
            {
                id: brandLabelText
                text: replaceText(materialBrandMenu.text)
                Layout.fillWidth: true
                Layout.fillHeight:true
                elide: Label.ElideRight
                wrapMode: Text.NoWrap
            }

            Item
            {
                Layout.fillWidth: true
            }

            Item
            {
                // Right side margin
                width: UM.Theme.getSize("default_margin").width
            }
        }

        onEntered: showTimer.restartTimer()
        onExited: hideTimer.restartTimer()
    }

    Timer
    {
        id: showTimer
        interval: 250
        function restartTimer()
        {
            restart();
            running = Qt.binding(function() { return materialBrandMenu.enabled && materialBrandMenu.contentItem.containsMouse; });
            hideTimer.running = false;
        }
        onTriggered: menuPopup.open()
    }
    Timer
    {
        id: hideTimer
        interval: 250
        function restartTimer()
        {
            restart();
            running = Qt.binding(function() { return materialBrandMenu.enabled && !materialBrandMenu.contentItem.containsMouse && !menuPopup.itemHovered > 0; });
            showTimer.running = false;
        }
        onTriggered: menuPopup.close()
    }

    MaterialBrandSubMenu
    {
        id: menuPopup

        property int itemHovered: 0

        MouseArea
        {
            anchors.fill: parent
            hoverEnabled: true
            onEntered: hideTimer.restartTimer()
        }

        Column
        {
            id: materialTypesList
            width: UM.Theme.getSize("menu").width
            height: childrenRect.height
            spacing: 0

            property var brandMaterials: materialTypesModel.material_types

            Repeater
            {
                model: parent.brandMaterials
                delegate: Column
                {
                    width: UM.Theme.getSize("menu").width
                    height: childrenRect.height
                    spacing: 0

                    property var typeColors: model.colors

                    Repeater
                    {
                        model: parent.typeColors
                        delegate: Rectangle
                        {
                            height: UM.Theme.getSize("menu").height
                            width: UM.Theme.getSize("menu").width

                            color: materialColorButton.containsMouse ? UM.Theme.getColor("background_2") : UM.Theme.getColor("main_background")

                            MouseArea
                            {
                                id: materialColorButton
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked:
                                {
                                    Cura.MachineManager.setMaterial(extruderIndex, model.container_node);
                                    menuPopup.close();
                                    materialMenu.close();
                                }
                                onEntered: menuPopup.itemHovered += 1
                                onExited: menuPopup.itemHovered -= 1
                            }

                            Item
                            {
                                height: parent.height
                                width: parent.width
                                opacity: materialBrandMenu.enabled ? 1 : 0.5
                                anchors.fill: parent

                                UM.ColorImage
                                {
                                    id: checkmark
                                    visible: model.id === materialMenu.activeMaterialId
                                    height: UM.Theme.getSize("default_arrow").height
                                    width: height
                                    anchors.left: parent.left
                                    anchors.leftMargin: UM.Theme.getSize("default_margin").width
                                    anchors.verticalCenter: parent.verticalCenter
                                    source: UM.Theme.getIcon("Check", "low")
                                    color: UM.Theme.getColor("setting_control_text")
                                }

                                UM.Label
                                {
                                    text: model.name
                                    anchors.left: parent.left
                                    anchors.leftMargin: UM.Theme.getSize("default_margin").width + UM.Theme.getSize("default_arrow").height
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.right: parent.right
                                    anchors.rightMargin: UM.Theme.getSize("default_margin").width
                                    elide: Label.ElideRight
                                    wrapMode: Text.NoWrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }

}
