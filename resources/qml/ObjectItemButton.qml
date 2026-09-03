// Copyright (c) 2020 Ultimaker B.V.
// Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.10
import QtQuick.Controls 2.3

import UM 1.5 as UM
import Cura 1.0 as Cura

Button
{
    id: objectItemButton

    width: parent.width
    height: UM.Theme.getSize("action_button").height
    checkable: true
    hoverEnabled: true

    // PrintessFlow: rows carry a grip that drags them into a new print position.
    // The grip is a separate handle rather than the whole row on purpose: a drag
    // started anywhere on the row would have to swallow the press and then
    // re-implement selection, the tooltip and the per-object settings button
    // underneath it, and get all three right. A handle touches none of them.
    property var listViewRef: objectItemButton.ListView.view
    // Checked for truth, not against null: an unattached ListView.view is
    // undefined, and reading dropTargetIndex off that is a TypeError.
    property bool dropTarget: listViewRef ? listViewRef.dropTargetIndex === index : false

    onHoveredChanged:
    {
        if(hovered && (buttonTextMetrics.elidedText != buttonText.text || perObjectSettingsInfo.visible))
        {
            tooltip.show()
        } else
        {
            tooltip.hide()
        }
    }


    onClicked: Cura.SceneController.changeSelection(index)

    background: Rectangle
    {
        id: backgroundRect
        color: (objectItemButton.hovered || objectItemButton.dropTarget) ? UM.Theme.getColor("action_button_hovered") : "transparent"
        radius: UM.Theme.getSize("action_button_radius").width
        border.width: UM.Theme.getSize("default_lining").width
        // The row a drag would land on is outlined the same way the selected row
        // is, so the position being chosen is the thing being looked at.
        border.color: (objectItemButton.checked || objectItemButton.dropTarget) ? UM.Theme.getColor("primary") : "transparent"
    }

    contentItem: Item
    {
        width: objectItemButton.width - objectItemButton.leftPadding
        height: UM.Theme.getSize("action_button").height

        Item
        {
            id: dragHandle
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            width: UM.Theme.getSize("standard_arrow").height
            height: UM.Theme.getSize("standard_arrow").height

            // Six dots drawn with rectangles rather than a themed icon, so no new
            // SVG has to ship. That is not only about the file count: a stroked
            // path is what crashes Qt6Svg at startup, and this needs no path.
            Grid
            {
                anchors.centerIn: parent
                columns: 2
                spacing: Math.max(1, Math.round(dragHandle.height / 7))

                Repeater
                {
                    model: 6
                    Rectangle
                    {
                        width: Math.max(1, Math.round(dragHandle.height / 7))
                        height: width
                        radius: Math.round(width / 2)
                        color: UM.Theme.getColor("text_scene")
                        opacity: dragArea.pressed ? 1.0 : (objectItemButton.hovered ? 0.8 : 0.4)
                    }
                }
            }

            MouseArea
            {
                id: dragArea
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                cursorShape: Qt.SizeVerCursor
                // The ListView would otherwise take the drag for a flick and
                // steal it halfway through.
                preventStealing: true

                property int targetIndex: -1

                // Which row the pointer is over, in the view's own coordinates so
                // that a list scrolled part way down still answers correctly.
                function rowUnder(mouseY)
                {
                    var view = objectItemButton.listViewRef;
                    if (!view)
                    {
                        return index;
                    }
                    var point = mapToItem(view.contentItem, width / 2, mouseY);
                    var found = view.indexAt(point.x, point.y);
                    if (found >= 0)
                    {
                        return found;
                    }
                    // Dragged off one end of the list: read that as first or last
                    // rather than as nothing, which is what indexAt reports in the
                    // gap between rows as well.
                    return point.y < 0 ? 0 : view.count - 1;
                }

                function setTarget(newTarget)
                {
                    targetIndex = newTarget;
                    if (objectItemButton.listViewRef)
                    {
                        objectItemButton.listViewRef.dropTargetIndex = newTarget;
                    }
                }

                function clearTarget()
                {
                    if (objectItemButton.listViewRef)
                    {
                        objectItemButton.listViewRef.dropTargetIndex = -1;
                    }
                    targetIndex = -1;
                }

                onPressed: setTarget(index)

                onPositionChanged: (mouse) => setTarget(rowUnder(mouse.y))

                onReleased:
                {
                    var landing = targetIndex;
                    clearTarget();
                    if (landing >= 0 && landing !== index)
                    {
                        Cura.PrintessPrintOrder.moveObject(index, landing);
                    }
                }

                onCanceled: clearTarget()
            }
        }

        Rectangle
        {
            id: swatch
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: dragHandle.right
            anchors.leftMargin: UM.Theme.getSize("narrow_margin").width
            width: UM.Theme.getSize("standard_arrow").height
            height: UM.Theme.getSize("standard_arrow").height
            radius: Math.round(width / 2)
            color: extruderColor
            visible: showExtruderSwatches && extruderColor != ""
        }

        UM.Label
        {
            id: buttonText
            anchors
            {
                left: showExtruderSwatches ? swatch.right : dragHandle.right
                leftMargin: UM.Theme.getSize("narrow_margin").width
                right: perObjectSettingsInfo.visible ? perObjectSettingsInfo.left : parent.right
                verticalCenter: parent.verticalCenter
            }
            text: objectItemButton.text
            color: UM.Theme.getColor("text_scene")
            opacity: (outsideBuildArea) ? 0.5 : 1.0
            visible: text != ""
            elide: Text.ElideRight
        }

        Button
        {
            id: perObjectSettingsInfo

            anchors
            {
                right: parent.right
                rightMargin: 0
            }
            width: meshTypeIcon.width + perObjectSettingsCountLabel.width + UM.Theme.getSize("narrow_margin").width
            height: parent.height
            padding: 0
            leftPadding: UM.Theme.getSize("thin_margin").width
            visible: meshType != "" || perObjectSettingsCount > 0

            onClicked:
            {
                Cura.SceneController.changeSelection(index)
                UM.Controller.setActiveTool("PerObjectSettingsTool")
            }

            property string tooltipText:
            {
                var result = "";
                if (!visible)
                {
                    return result;
                }
                if (meshType != "")
                {
                    result += "<br>";
                    switch (meshType) {
                        case "support_mesh":
                            result += catalog.i18nc("@label", "Is printed as support.");
                            break;
                        case "cutting_mesh":
                            result += catalog.i18nc("@label", "Other models overlapping with this model are modified.");
                            break;
                        case "infill_mesh":
                            result += catalog.i18nc("@label", "Infill overlapping with this model is modified.");
                            break;
                        case "anti_overhang_mesh":
                            result += catalog.i18nc("@label", "Overlaps with this model are not supported.");
                            break;
                    }
                }
                if (perObjectSettingsCount != "")
                {
                    result += "<br>" + catalog.i18ncp(
                        "@label %1 is the number of settings it overrides.", "Overrides %1 setting.", "Overrides %1 settings.", perObjectSettingsCount
                    ).arg(perObjectSettingsCount);
                }
                return result;
            }

            contentItem: Item
            {
                height: parent.height
                width: perObjectSettingsInfo.width

                Cura.NotificationIcon
                {
                    id: perObjectSettingsCountLabel
                    anchors
                    {
                        right: parent.right
                        rightMargin: 0
                    }
                    visible: perObjectSettingsCount > 0
                    color: UM.Theme.getColor("text_scene")
                    labelText: perObjectSettingsCount.toString()
                }

                UM.ColorImage
                {
                    id: meshTypeIcon
                    anchors
                    {
                        right: perObjectSettingsCountLabel.left
                        rightMargin: UM.Theme.getSize("narrow_margin").width
                    }

                    width: parent.height
                    height: parent.height
                    color: UM.Theme.getColor("text_scene")
                    visible: meshType != ""
                    source:
                    {
                        switch (meshType) {
                            case "support_mesh":
                                return UM.Theme.getIcon("MeshTypeSupport");
                            case "cutting_mesh":
                            case "infill_mesh":
                                return UM.Theme.getIcon("MeshTypeIntersect");
                            case "anti_overhang_mesh":
                                return UM.Theme.getIcon("BlockSupportOverlaps");
                        }
                        return "";
                    }
                }
            }

            background: Item {}
        }
    }

    TextMetrics
    {
        id: buttonTextMetrics
        text: buttonText.text
        font: buttonText.font
        elide: buttonText.elide
        elideWidth: buttonText.width
    }

    UM.ToolTip
    {
        id: tooltip
        tooltipText: objectItemButton.text + perObjectSettingsInfo.tooltipText
    }

    UM.I18nCatalog
    {
        id: catalog
        name: "cura"
    }
}
