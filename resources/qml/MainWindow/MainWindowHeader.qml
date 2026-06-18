// Copyright (c) 2021 Ultimaker B.V.
// Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.7
import QtQuick.Controls 2.4

import UM 1.5 as UM
import Cura 1.0 as Cura

import "../Account"
import "../ApplicationSwitcher"

Item
{
    id: base

    implicitHeight: UM.Theme.getSize("main_window_header").height
    implicitWidth: UM.Theme.getSize("main_window_header").width

    Rectangle
    {
        anchors.fill: parent
        color: UM.Theme.getColor("main_window_header_background")
        clip: true

        Canvas
        {
            anchors.fill: parent
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()

            onPaint:
            {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var w = width
                var h = height
                var midY = h / 2

                // 5 concentric rings per shape, matching website HeroShapes.tsx
                var RING_SCALES = [1.0, 0.78, 0.56, 0.34, 0.12]
                var BASE_SCALE  = 0.55

                function drawRings(pathFn, cx, shapeOpacity, rotDeg)
                {
                    for (var i = 0; i < RING_SCALES.length; i++)
                    {
                        var s = RING_SCALES[i] * BASE_SCALE
                        ctx.save()
                        ctx.translate(cx, midY)
                        ctx.rotate((rotDeg || 0) * Math.PI / 180)
                        ctx.scale(s, s)
                        var grad = ctx.createLinearGradient(-50, 0, 50, 0)
                        grad.addColorStop(0, "rgba(255,255,255,0.95)")
                        grad.addColorStop(1, "rgba(151,189,217,0.90)")
                        ctx.strokeStyle = grad
                        ctx.lineWidth   = 1.4
                        ctx.globalAlpha = shapeOpacity * 0.85
                        ctx.beginPath()
                        pathFn()
                        ctx.stroke()
                        ctx.restore()
                    }
                }

                // Exact paths from HeroShapes.tsx
                function pathAstroid()
                {
                    ctx.moveTo(40, 0)
                    ctx.bezierCurveTo(24.4, 0, 0, 24.4, 0, 40)
                    ctx.bezierCurveTo(0, 24.4, -24.4, 0, -40, 0)
                    ctx.bezierCurveTo(-24.4, 0, 0, -24.4, 0, -40)
                    ctx.bezierCurveTo(0, -24.4, 24.4, 0, 40, 0)
                    ctx.closePath()
                }

                function pathSnowflake()
                {
                    ctx.moveTo(0, -42)
                    ctx.lineTo(9, -15.6)
                    ctx.lineTo(36.4, -21)
                    ctx.lineTo(18, 0)
                    ctx.lineTo(36.4, 21)
                    ctx.lineTo(9, 15.6)
                    ctx.lineTo(0, 42)
                    ctx.lineTo(-9, 15.6)
                    ctx.lineTo(-36.4, 21)
                    ctx.lineTo(-18, 0)
                    ctx.lineTo(-36.4, -21)
                    ctx.lineTo(-9, -15.6)
                    ctx.closePath()
                }

                function pathDeltoid()
                {
                    ctx.moveTo(0, -31.5)
                    ctx.bezierCurveTo(0, -12.83, 20.20, 22.17, 36.37, 31.5)
                    ctx.bezierCurveTo(20.20, 22.17, -20.20, 22.17, -36.37, 31.5)
                    ctx.bezierCurveTo(-20.20, 22.17, 0, -12.83, 0, -31.5)
                    ctx.closePath()
                }

                function pathLemniscate()
                {
                    ctx.moveTo(0, 0)
                    ctx.bezierCurveTo(10, 22, 34, 22, 42, 0)
                    ctx.bezierCurveTo(34, -22, 10, -22, 0, 0)
                    ctx.bezierCurveTo(-10, -22, -34, -22, -42, 0)
                    ctx.bezierCurveTo(-34, 22, -10, 22, 0, 0)
                    ctx.closePath()
                }

                function pathRoseCurve()
                {
                    ctx.moveTo(0, 0)
                    ctx.bezierCurveTo(12, 18, 34, 14, 40, 0)
                    ctx.bezierCurveTo(34, -14, 12, -18, 0, 0)
                    ctx.bezierCurveTo(-21.6, 1.4, -29.1, 22.4, -20, 34.6)
                    ctx.bezierCurveTo(-4.9, 36.4, 9.6, 19.4, 0, 0)
                    ctx.bezierCurveTo(9.6, -19.4, -4.9, -36.4, -20, -34.6)
                    ctx.bezierCurveTo(-29.1, -22.4, -21.6, -1.4, 0, 0)
                    ctx.closePath()
                }

                // 4 contour lines flowing from right to left
                // [yFrac, strokeWidth, opacity, cp1yDelta, cp2yDelta, cp3yDelta, cp4yDelta]
                var contours = [
                    [0.22, 2.0, 0.42,  0.12, -0.14,  0.10, -0.08],
                    [0.50, 2.5, 0.52, -0.13,  0.15, -0.11,  0.09],
                    [0.78, 2.0, 0.42,  0.11, -0.15,  0.13, -0.10],
                ]

                // Pre-compute element positions used by both contours and shapes
                var stagesL = stagesListContainer.mapToItem(base, 0, 0).x
                var stagesR = stagesListContainer.mapToItem(base, stagesListContainer.width, 0).x
                var brandR  = brandingRow.mapToItem(base, brandingRow.width, 0).x

                // Lines flow right to left, stopping just before the branding text.
                // Clipped to skip the stage-button region so buttons stay unobstructed.
                var stopX = brandR + 12
                var span  = w - stopX

                for (var ci = 0; ci < contours.length; ci++)
                {
                    var c = contours[ci]
                    var y = h * c[0]
                    var grad = ctx.createLinearGradient(w, 0, stopX, 0)
                    grad.addColorStop(0.00, "rgba(255,255,255," + c[2] + ")")
                    grad.addColorStop(0.40, "rgba(151,189,217," + (c[2] * 0.85).toFixed(2) + ")")
                    grad.addColorStop(0.75, "rgba(151,189,217," + (c[2] * 0.45).toFixed(2) + ")")
                    grad.addColorStop(1.00, "rgba(151,189,217,0)")
                    ctx.strokeStyle = grad
                    ctx.lineWidth   = c[1]
                    ctx.globalAlpha = 1.0
                    ctx.beginPath()
                    ctx.moveTo(w + 20, y)
                    ctx.bezierCurveTo(stopX + span * 0.78, y + h * c[3], stopX + span * 0.56, y + h * c[4], stopX + span * 0.45, y + h * (c[3] + c[4]) / 2)
                    ctx.bezierCurveTo(stopX + span * 0.32, y + h * c[5], stopX + span * 0.15, y + h * c[6], stopX, y)
                    ctx.stroke()
                }

                // Shapes positioned across the header width, vertically centred.
                // Clip to avoid overlapping the logo/text and the stage buttons.
                var shapeRadius = Math.ceil(BASE_SCALE * 44) + 6
                var bRight = brandR  + shapeRadius
                var sLeft  = stagesL - shapeRadius
                var sRight = stagesR + shapeRadius

                ctx.save()
                ctx.beginPath()
                ctx.rect(bRight, 0, Math.max(0, sLeft - bRight), h)   // between branding and stages
                ctx.rect(sRight, 0, Math.max(0, w - sRight), h)        // right of stages
                ctx.clip()

                var z1s = bRight, z1e = sLeft
                var z2s = sRight, z2e = w

                drawRings(pathLemniscate, z1s + (z1e - z1s) * 0.33, 0.78,  45)
                drawRings(pathDeltoid,    z1s + (z1e - z1s) * 0.70, 0.75, -30)

                drawRings(pathSnowflake,  z2s + (z2e - z2s) * 0.20, 0.80,  15)
                drawRings(pathAstroid,    z2s + (z2e - z2s) * 0.55, 0.78, 22.5)
                drawRings(pathRoseCurve,  z2s + (z2e - z2s) * 0.85, 0.75, -30)

                ctx.restore()
            }
        }
    }

    Row
    {
        id: brandingRow
        anchors.left: parent.left
        anchors.leftMargin: UM.Theme.getSize("default_margin").width
        anchors.verticalCenter: parent.verticalCenter
        spacing: UM.Theme.getSize("narrow_margin").width

        Image
        {
            id: logo
            anchors.verticalCenter: parent.verticalCenter
            source: "../../images/printess_logo.png"
            height: UM.Theme.getSize("logo").height
            fillMode: Image.PreserveAspectFit
            sourceSize.height: height * 2
        }
    }
    ButtonGroup
    {
        buttons: stagesListContainer.children
    }

    Item
    {
        anchors.left: brandingRow.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom

    Row
    {
        id: stagesListContainer
        spacing: Math.round(UM.Theme.getSize("default_margin").width / 2)

        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter

        // The main window header is dynamically filled with all available stages
        Repeater
        {
            id: stagesHeader

            model: UM.StageModel { }

            delegate: Button
            {
                id: stageSelectorButton
                text: model.name.toUpperCase()
                checkable: true
                checked: UM.Controller.activeStage !== null && model.id == UM.Controller.activeStage.stageId
                visible: model.id !== "MonitorStage"

                anchors.verticalCenter: parent.verticalCenter
                //style: UM.Theme.styles.main_window_header_tab
                height: Math.round(0.5 * UM.Theme.getSize("main_window_header").height)
                // This id is required to find the stage buttons through Squish
                property string stageId: model.id
                hoverEnabled: true
                leftPadding: 2 * UM.Theme.getSize("default_margin").width
                rightPadding: 2 * UM.Theme.getSize("default_margin").width

                // Set top & bottom padding to whatever space is left from height and the size of the text.
                bottomPadding: Math.round((height - buttonLabel.contentHeight) / 2)
                topPadding: bottomPadding

                background: Rectangle
                {
                    radius: UM.Theme.getSize("action_button_radius").width
                    color:
                    {
                        if (stageSelectorButton.checked)
                        {
                            return UM.Theme.getColor("main_window_header_button_background_active")
                        }
                        else
                        {
                            if (stageSelectorButton.hovered)
                            {
                                return UM.Theme.getColor("main_window_header_button_background_hovered")
                            }
                            return UM.Theme.getColor("main_window_header_button_background_inactive")
                        }
                    }
                }

                contentItem: UM.Label
                {
                    id: buttonLabel
                    text: stageSelectorButton.text
                    anchors.centerIn: stageSelectorButton
                    font: UM.Theme.getFont("medium")
                    color:
                    {
                        if (stageSelectorButton.checked)
                        {
                            return UM.Theme.getColor("main_window_header_button_text_active")
                        }
                        else
                        {
                            if (stageSelectorButton.hovered)
                            {
                                return UM.Theme.getColor("main_window_header_button_text_hovered")
                            }
                            return UM.Theme.getColor("main_window_header_button_text_inactive")
                        }
                    }
                }

                // This is a trick to assure the activeStage is correctly changed. It doesn't work properly if done in the onClicked (see CURA-6028)
                MouseArea
                {
                    anchors.fill: parent
                    onClicked: UM.Controller.setActiveStage(model.id)
                }
            }
        }
    }
    }

    // Shortcut button to quick access the Toolbox
    Button
    {
        id: marketplaceButton
        visible: false
        text: catalog.i18nc("@action:button", "Marketplace")
        height: Math.round(0.5 * UM.Theme.getSize("main_window_header").height)
        onClicked: Cura.Actions.browsePackages.trigger()

        hoverEnabled: true

        background: Rectangle
        {
            id: marketplaceButtonBorder
            radius: UM.Theme.getSize("action_button_radius").width
            color: UM.Theme.getColor("main_window_header_background")
            border.width: UM.Theme.getSize("default_lining").width
            border.color: UM.Theme.getColor("primary_text")

            Rectangle
            {
                id: marketplaceButtonFill
                anchors.fill: parent
                radius: parent.radius
                color: UM.Theme.getColor("primary_text")
                opacity: marketplaceButton.hovered ? 0.2 : 0
                Behavior on opacity { NumberAnimation { duration: 100 } }
            }
        }

        contentItem: UM.Label
        {
            id: label
            text: marketplaceButton.text
            color: UM.Theme.getColor("primary_text")
            width: contentWidth
        }

        anchors
        {
            right: applicationSwitcher.left
            rightMargin: UM.Theme.getSize("default_margin").width
            verticalCenter: parent.verticalCenter
        }

        Cura.NotificationIcon
        {
            id: marketplaceNotificationIcon
            anchors
            {
                top: parent.top
                right: parent.right
                rightMargin: (-0.5 * width) | 0
                topMargin: (-0.5 * height) | 0
            }
            visible: CuraApplication.getPackageManager().packagesWithUpdate.length > 0

            labelText:
            {
                const itemCount = CuraApplication.getPackageManager().packagesWithUpdate.length
                return itemCount > 9 ? "9+" : itemCount
            }
        }
    }

    ApplicationSwitcher
    {
        id: applicationSwitcher
        visible: false
        anchors
        {
            verticalCenter: parent.verticalCenter
            right: accountWidget.left
            rightMargin: UM.Theme.getSize("default_margin").width
        }
    }

    AccountWidget
    {
        id: accountWidget
        visible: false
        anchors
        {
            verticalCenter: parent.verticalCenter
            right: parent.right
            rightMargin: UM.Theme.getSize("default_margin").width
        }
    }
}
