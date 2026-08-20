// Copyright (c) 2022 Ultimaker B.V.
// Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.7
import QtQuick.Controls 2.4
import QtQuick.Layouts 1.3

import UM 1.5 as UM
import Cura 1.0 as Cura


// This element contains all the elements the user needs to create a printjob from the
// model(s) that is(are) on the buildplate. Mainly the button to start/stop the slicing
// process and a progress bar to see the progress of the process.
Column
{
    id: widget

    spacing: UM.Theme.getSize("thin_margin").height

    UM.I18nCatalog
    {
        id: catalog
        name: "cura"
    }

    property real progress: UM.Backend.progress
    property int backendState: UM.Backend.state
    // As the collection of settings to send to the engine might take some time, we have an extra value to indicate
    // That the user pressed the button but it's still waiting for the backend to acknowledge that it got it.
    property bool waitingForSliceToStart: false
    onBackendStateChanged: waitingForSliceToStart = false

    function sliceOrStopSlicing()
    {
        if (widget.backendState == UM.Backend.NotStarted)
        {
            widget.waitingForSliceToStart = true
            CuraApplication.backend.forceSlice()
        }
        else
        {
            widget.waitingForSliceToStart = false
            CuraApplication.backend.stopSlicing()
        }
    }

    UM.Label
    {
        id: autoSlicingLabel
        width: parent.width
        visible: progressBar.visible

        text: catalog.i18nc("@label:PrintjobStatus", "Slicing...")
    }
    Item
    {
        id: unableToSliceMessage
        width: parent.width
        visible: widget.backendState == UM.Backend.Error

        height: warningIcon.height
        UM.StatusIcon
        {
            id: warningIcon
            anchors.verticalCenter: parent.verticalCenter
            width: visible ? UM.Theme.getSize("section_icon").width : 0
            height: width
            status: UM.StatusIcon.Status.WARNING
        }
        UM.Label
        {
            id: label
            anchors.left: warningIcon.right
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: UM.Theme.getSize("default_margin").width
            text: catalog.i18nc("@label:PrintjobStatus", "Unable to slice")
            wrapMode: Text.WordWrap
        }
    }

    // Progress bar, only visible when the backend is in the process of slice the printjob
    UM.ProgressBar
    {
        id: progressBar
        width: parent.width
        height: UM.Theme.getSize("progressbar").height
        value: progress
        indeterminate: widget.backendState == UM.Backend.NotStarted
        visible: (widget.backendState == UM.Backend.Processing || (prepareButtons.autoSlice && widget.backendState == UM.Backend.NotStarted))
    }

    // Printess: XY homing toggle + zero-offset fields, shown directly above the Slice
    // button. This whole widget is unloaded once output is available, so the section is
    // automatically hidden after slicing. The state is stored in preferences and read by
    // the Printess post-processing scripts, which build the startup homing (G28) + zero
    // (G92) block from it. Z and A are not homed at all, so they have no row here; see
    // the manual-zero warning below.
    Column
    {
        id: homingSection
        width: parent.width
        spacing: UM.Theme.getSize("narrow_margin").height
        bottomPadding: UM.Theme.getSize("narrow_margin").height

        // Width of each numeric zero-offset field.
        readonly property real offsetFieldWidth: Math.round(UM.Theme.getSize("setting_control").width * 0.45)

        // Thin divider that separates the homing options from the controls above.
        Rectangle
        {
            width: parent.width
            height: UM.Theme.getSize("default_lining").height
            color: UM.Theme.getColor("lining")
        }

        UM.Label
        {
            text: catalog.i18nc("@label", "Homing")
            // Printess brand red — the same tone as the main window header.
            color: UM.Theme.getColor("main_window_header_button_text_active")
            font: UM.Theme.getFont("default_bold")
        }

        // Row: XY homing toggle + X / Y zero-offset fields.
        RowLayout
        {
            width: parent.width
            spacing: UM.Theme.getSize("narrow_margin").width

            UM.CheckBox
            {
                id: homeXYCheckbox
                text: catalog.i18nc("@option:check", "XY Axes")
                // Indent the toggles slightly under the section title.
                leftPadding: UM.Theme.getSize("default_margin").width
                checked: UM.Preferences.getValue("printess/home_xy")
                onClicked: UM.Preferences.setValue("printess/home_xy", checked)
            }

            // Spacer that right-aligns the offset fields.
            Item { Layout.fillWidth: true }

            UM.Label { text: catalog.i18nc("@label", "X"); Layout.alignment: Qt.AlignVCenter }
            Cura.TextField
            {
                id: offsetXField
                Layout.preferredWidth: homingSection.offsetFieldWidth
                Layout.alignment: Qt.AlignVCenter
                enabled: homeXYCheckbox.checked
                text: UM.Preferences.getValue("printess/zero_offset_x")
                validator: DoubleValidator { locale: "en_US"; notation: DoubleValidator.StandardNotation }
                onEditingFinished: UM.Preferences.setValue("printess/zero_offset_x", text)
            }

            UM.Label { text: catalog.i18nc("@label", "Y"); Layout.alignment: Qt.AlignVCenter }
            Cura.TextField
            {
                id: offsetYField
                Layout.preferredWidth: homingSection.offsetFieldWidth
                Layout.alignment: Qt.AlignVCenter
                enabled: homeXYCheckbox.checked
                text: UM.Preferences.getValue("printess/zero_offset_y")
                validator: DoubleValidator { locale: "en_US"; notation: DoubleValidator.StandardNotation }
                onEditingFinished: UM.Preferences.setValue("printess/zero_offset_y", text)
            }
        }

        // Caption clarifying the fields are per-axis zero offsets in millimeters.
        Item
        {
            width: parent.width
            height: offsetCaption.height
            UM.Label
            {
                id: offsetCaption
                anchors.right: parent.right
                text: catalog.i18nc("@label", "(zero offset, mm)")
                font: UM.Theme.getFont("small")
                color: UM.Theme.getColor("text_inactive")
            }
        }
    }

    // Printess: Z and A are never homed, so the print starts from wherever the operator
    // last zeroed them. Nothing in the g-code can check that, which makes this reminder
    // the only guard against driving a syringe into the plate. Sits directly above the
    // Slice button so it is read at the moment the file is made.
    Item
    {
        id: manualZeroWarning
        width: parent.width
        height: Math.max(manualZeroIcon.height, manualZeroLabel.implicitHeight)

        UM.StatusIcon
        {
            id: manualZeroIcon
            width: UM.Theme.getSize("section_icon").width
            height: width
            status: UM.StatusIcon.Status.WARNING
        }

        UM.Label
        {
            id: manualZeroLabel
            anchors.left: manualZeroIcon.right
            anchors.right: parent.right
            anchors.leftMargin: UM.Theme.getSize("thin_margin").width
            // Deliberately the plain "text" color, not "text_detail": the detail tone is
            // half-alpha and unreadable, and this is the one label that must not be missed.
            color: UM.Theme.getColor("text")
            wrapMode: Text.WordWrap
            text: catalog.i18nc("@label", "Zero the used syringe axes with G92 on Pronterface before printing")
        }
    }

    Item
    {
        id: prepareButtons
        // Get the current value from the preferences
        property bool autoSlice: UM.Preferences.getValue("general/auto_slice")
        // Disable the slice process when

        width: parent.width
        height: UM.Theme.getSize("action_button").height
        visible: !autoSlice
        Cura.PrimaryButton
        {
            id: sliceButton
            fixedWidthMode: true

            // Matches Draw Paths, Well Plate Arranger and the script selector
            // beside it. ActionButton defaults to "medium", which left this the
            // odd one out in a row of otherwise identical buttons.
            textFont: UM.Theme.getFont("medium_bold")

            height: parent.height

            anchors.right: parent.right
            anchors.left: parent.left

            text: widget.waitingForSliceToStart ? catalog.i18nc("@button", "Processing"): catalog.i18nc("@button", "Slice")
            tooltip: catalog.i18nc("@label", "Start the slicing process")
            hoverEnabled: !widget.waitingForSliceToStart
            // Nothing to slice on an empty plate. Stock Cura got this for free by
            // hiding the whole panel; the panel is permanent here, so the button
            // carries the condition itself. Greyed rather than hidden, so the bar
            // keeps its shape instead of the button coming and going.
            enabled: widget.backendState != UM.Backend.Error && !widget.waitingForSliceToStart
                     && CuraApplication.platformActivity
            visible: widget.backendState == UM.Backend.NotStarted || widget.backendState == UM.Backend.Error
            onClicked: {
                sliceOrStopSlicing()
            }
        }

        Cura.SecondaryButton
        {
            id: cancelButton
            fixedWidthMode: true
            // Same button, same place, different state: it has to match Slice or
            // the text changes size the moment slicing starts.
            textFont: UM.Theme.getFont("medium_bold")
            height: parent.height
            anchors.left: parent.left

            anchors.right: parent.right
            text: catalog.i18nc("@button", "Cancel")
            enabled: sliceButton.enabled
            visible: !sliceButton.visible
            onClicked: {
                sliceOrStopSlicing()
            }
        }
    }


    // React when the user changes the preference of having the auto slice enabled
    Connections
    {
        target: UM.Preferences
        function onPreferenceChanged(preference)
        {
            if (preference !== "general/auto_slice")
            {
                return;
            }

            var autoSlice = UM.Preferences.getValue("general/auto_slice")
            if(prepareButtons.autoSlice != autoSlice)
            {
                prepareButtons.autoSlice = autoSlice
                if(autoSlice)
                {
                    CuraApplication.backend.forceSlice()
                }
            }
        }
    }

    // Shortcut for "slice/stop"
    Action
    {
        shortcut: "Ctrl+P"
        onTriggered:
        {
            if (sliceButton.enabled)
            {
                sliceOrStopSlicing()
            }
        }
    }
}
