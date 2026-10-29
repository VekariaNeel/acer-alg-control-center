// SPDX-License-Identifier: GPL-2.0-only
/*
 * Acer Aspire Lite AL15G-52 firmware control bridge, ABI 2.
 *
 * Original implementation based on the operator's firmware disassembly and
 * InsydeDCHU.dll transport evidence. No vendor source is incorporated.
 * Typed, root-only setters. No arbitrary methods, raw EC access, polling
 * worker or initialization-time firmware calls. See PROTOCOL.md.
 */
#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/delay.h>
#include <linux/hex.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/sysfs.h>
#include <linux/uuid.h>
#include "acer_protocol.h"

#define CC_SIZE 256
#define CC_NAME "acer_al15g52"

struct cc_device {
	acpi_handle handle;
	struct mutex lock;
	guid_t uuid;
	int sleep_seconds; /* Last acknowledged request, NOT a firmware getter. */
};

static const struct dmi_system_id cc_models[] = {
	{
		.matches = {
			DMI_EXACT_MATCH(DMI_SYS_VENDOR, "Acer"),
			DMI_EXACT_MATCH(DMI_PRODUCT_NAME, "Aspire Lite AL15G-52"),
			DMI_EXACT_MATCH(DMI_BIOS_VERSION, "1.07.01RAC2"),
		},
	},
	{ }
};

/* Called only with the transaction mutex held. Fixed internal callers select
 * function/payload; no sysfs interface accepts raw commands or ACPI paths. */
static int cc_call_locked(struct cc_device *cc, u32 function, const u8 *input,
			  u8 *output, u64 *integer)
{
	union acpi_object argument = {
		.buffer = { .type = ACPI_TYPE_BUFFER, .length = CC_SIZE,
			    .pointer = (u8 *)input },
	};
	union acpi_object package = {
		.package = { .type = ACPI_TYPE_PACKAGE, .count = 1,
			     .elements = &argument },
	};
	union acpi_object *result;
	int error = 0;

	result = acpi_evaluate_dsm(cc->handle, &cc->uuid, 0, function, &package);
	if (!result) {
		error = -EIO;
	} else if (output && result->type == ACPI_TYPE_BUFFER &&
		   result->buffer.length == CC_SIZE && result->buffer.pointer) {
		memcpy(output, result->buffer.pointer, CC_SIZE);
	} else if (integer && result->type == ACPI_TYPE_INTEGER) {
		*integer = result->integer.value;
	} else if (!output && !integer &&
		   ((result->type == ACPI_TYPE_INTEGER &&
		     result->integer.value == (function == 14 ? 20 : function)) ||
		    (function == 4 && result->type == ACPI_TYPE_BUFFER &&
		     result->buffer.length == CC_SIZE))) {
		/* Setter acknowledgement; semantic readback is performed below. */
	} else {
		error = -EPROTO;
	}
	ACPI_FREE(result);
	return error;
}

static int cc_read_locked(struct cc_device *cc, u32 function, u8 sub, u8 *output)
{
	u8 input[CC_SIZE] = { 0 };
	input[0] = sub;
	return cc_call_locked(cc, function, input, output, NULL);
}

static int cc_get_buffer(struct cc_device *cc, u32 function, u8 sub, u8 *output)
{
	int error;
	mutex_lock(&cc->lock);
	error = cc_read_locked(cc, function, sub, output);
	mutex_unlock(&cc->lock);
	return error;
}

static ssize_t cc_show_buffer(struct device *device, char *buffer,
			      u32 function, u8 subcommand)
{
	struct cc_device *cc = dev_get_drvdata(device);
	u8 data[CC_SIZE];
	int error;

	error = cc_get_buffer(cc, function, subcommand, data);
	if (error)
		return error;
	bin2hex(buffer, data, CC_SIZE);
	buffer[CC_SIZE * 2] = '\n';
	return CC_SIZE * 2 + 1;
}

static ssize_t telemetry_show(struct device *device,
			       struct device_attribute *attribute, char *buffer)
{
	return cc_show_buffer(device, buffer, 0x0c, 0);
}
static DEVICE_ATTR_RO(telemetry);

static ssize_t specs_show(struct device *device,
			   struct device_attribute *attribute, char *buffer)
{
	return cc_show_buffer(device, buffer, 0x0d, 0);
}
static DEVICE_ATTR_RO(specs);

static ssize_t charging_show(struct device *device,
			      struct device_attribute *attribute, char *buffer)
{
	return cc_show_buffer(device, buffer, 0x04, 0x1e);
}
static DEVICE_ATTR_RO(charging);

static ssize_t abi_version_show(struct device *device,
				 struct device_attribute *attribute, char *buffer)
{
	return sysfs_emit(buffer, "2\n");
}
static DEVICE_ATTR_RO(abi_version);

#include "acer_controls.h"

static struct attribute *cc_attributes[] = {
	&dev_attr_abi_version.attr,
	&dev_attr_telemetry.attr,
	&dev_attr_specs.attr,
	&dev_attr_charging.attr,
	&dev_attr_fan_mode.attr,
	&dev_attr_fan_offset.attr,
	&dev_attr_fan_curve.attr,
	&dev_attr_keyboard_rgb.attr,
	&dev_attr_keyboard_brightness.attr,
	&dev_attr_charge_limits.attr,
	&dev_attr_keyboard_flags.attr,
	&dev_attr_keyboard_sleep.attr,
	&dev_attr_camera.attr,
	&dev_attr_power_mode.attr,
	NULL,
};
static const struct attribute_group cc_group = {
	.name = "control_center",
	.attrs = cc_attributes,
};

static int cc_probe(struct platform_device *device)
{
	struct cc_device *cc;
	int error;

	if (!dmi_check_system(cc_models))
		return -ENODEV;
	if (!ACPI_HANDLE(&device->dev) ||
	    !acpi_has_method(ACPI_HANDLE(&device->dev), "_DSM"))
		return -ENODEV;
	cc = devm_kzalloc(&device->dev, sizeof(*cc), GFP_KERNEL);
	if (!cc)
		return -ENOMEM;
	cc->handle = ACPI_HANDLE(&device->dev);
	cc->sleep_seconds = -1;
	error = guid_parse("93f224e4-fbdc-4bbf-add6-db71bdc0afad", &cc->uuid);
	if (error)
		return error;
	mutex_init(&cc->lock);
	platform_set_drvdata(device, cc);
	error = devm_device_add_group(&device->dev, &cc_group);
	if (error)
		return error;
	dev_info(&device->dev, "AL15G-52 bridge ABI 2 ready; typed setters require root\n");
	return 0;
}

static const struct acpi_device_id cc_acpi_ids[] = {
	{ "CLV0001", 0 },
	{ }
};
MODULE_DEVICE_TABLE(acpi, cc_acpi_ids);

static struct platform_driver cc_driver = {
	.probe = cc_probe,
	.driver = {
		.name = CC_NAME,
		.acpi_match_table = cc_acpi_ids,
	},
};
module_platform_driver(cc_driver);

MODULE_DESCRIPTION("Acer AL15G-52 ACPI telemetry and typed controls");
MODULE_LICENSE("GPL");
MODULE_VERSION("0.5.1");
