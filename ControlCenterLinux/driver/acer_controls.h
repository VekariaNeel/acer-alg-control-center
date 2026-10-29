/* SPDX-License-Identifier: GPL-2.0-only */
/* Included by acer_al15g52.c. Every multi-command operation holds cc->lock. */

static int cc_named_locked(struct cc_device *cc, const char *name, u64 *value)
{
	return ACPI_FAILURE(acpi_evaluate_integer(cc->handle, (acpi_string)name,
						NULL, value)) ? -EIO : 0;
}

static int cc_state_locked(struct cc_device *cc, enum cc_action action, char *buf)
{
	u8 data[256];
	u64 value;
	int error, mode;
	u8 input[256] = { 0 };
	unsigned int i, length = 0;
	switch (action) {
	case CC_OFFSET:
		error = cc_named_locked(cc, "\\_SB.PC00.LPCB.EC.GFOF", &value);
		return error ? error : sysfs_emit(buf, "%llu\n", value);
	case CC_POWER:
		error = cc_named_locked(cc, "\\_SB.PC00.LPCB.EC.CPCM", &value);
		if (!error && value > 3) error = -EPROTO;
		return error ? error : sysfs_emit(buf, "%llu\n", value);
	case CC_SLEEP:
		return sysfs_emit(buf, "%d\n", cc->sleep_seconds);
	case CC_CAMERA:
		error = cc_call_locked(cc, 6, input, NULL, &value);
		if (!error && value > 1) error = -EOPNOTSUPP;
		return error ? error : sysfs_emit(buf, "%llu\n", value);
	case CC_CHARGE:
		error = cc_read_locked(cc, 4, 30, data);
		return error ? error : sysfs_emit(buf, "%u %u %u\n", data[0], data[1], data[2]);
	case CC_FLAGS:
		error = cc_read_locked(cc, 4, 24, data);
		return error ? error : sysfs_emit(buf, "%u %u %u\n", data[0], data[1], data[2]);
	default:
		error = cc_read_locked(cc, 13, 0, data);
		if (error) return error;
		if (data[12] != 2 || data[15] != 6) return -ENODEV;
		if (action == CC_FAN) {
			mode = cc_fan_mode(data[14]);
			return mode < 0 ? -EPROTO : sysfs_emit(buf, "%d\n", mode);
		}
		if (action == CC_BRIGHTNESS)
			return sysfs_emit(buf, "%u\n", data[11]);
		if (action == CC_RGB) {
			for (i = 2; i < 11; i++)
				length += sysfs_emit_at(buf, length, "%u%c", data[i], i == 10 ? '\n' : ' ');
			return length;
		}
		if (action == CC_CURVE) {
			for (i = 16; i < 32; i++)
				length += sysfs_emit_at(buf, length, "%u%c", (i & 1) ?
					(data[i] * 100 + 127) / 255 : data[i], i == 31 ? '\n' : ' ');
			return length;
		}
		return -EINVAL;
	}
}

static int cc_verify_locked(struct cc_device *cc, enum cc_action action,
			    const int *v, const struct cc_plan *plan)
{
	u8 data[256], input[256] = { 0 };
	u64 value;
	unsigned int i, p;
	int error;
	if (action == CC_CHARGE || action == CC_FLAGS) {
		error = cc_read_locked(cc, 4, action == CC_CHARGE ? 30 : 24, data);
		if (error) return error;
		return memcmp(data, plan->request[0].data + 1,
			      action == CC_CHARGE ? 3 : 5) ? -EIO : 0;
	}
	if (action == CC_OFFSET || action == CC_POWER) {
		error = cc_named_locked(cc, action == CC_OFFSET ?
			"\\_SB.PC00.LPCB.EC.GFOF" : "\\_SB.PC00.LPCB.EC.CPCM", &value);
		return error ? error : value == (action == CC_OFFSET ? cc_scale(v[0]) : v[0]) ? 0 : -EIO;
	}
	if (action == CC_SLEEP) {
		cc->sleep_seconds = v[0];
		return 0; /* Explicitly cached acknowledgement, not physical timer readback. */
	}
	if (action == CC_CAMERA) {
		error = cc_call_locked(cc, 6, input, NULL, &value);
		return error ? error : value == v[0] ? 0 : -EIO;
	}
	error = cc_read_locked(cc, 13, 0, data);
	if (error) return error;
	if (action == CC_FAN) return cc_fan_mode(data[14]) == v[0] ? 0 : -EIO;
	if (action == CC_CURVE) {
		for (i = 0; i < 2; i++) {
			p = 18 + i * 8;
			if (memcmp(data + p, plan->request[1].data + 2 + i * 4, 4)) return -EIO;
		}
		return 0;
	}
	/* RGB/brightness getters expose EC-native units. The scale relationship
	 * needs target validation: never fabricate logical/optical confirmation. */
	return 0;
}

static int cc_confirm_mode_locked(struct cc_device *cc, int mode)
{
	u8 data[256];
	int error, attempt;
	for (attempt = 0; attempt < 10; attempt++) {
		error = cc_read_locked(cc, 13, 0, data);
		if (error) return error;
		if (cc_fan_mode(data[14]) == mode) return 0;
		msleep(50);
	}
	return -EIO;
}

static ssize_t cc_store(struct device *device, enum cc_action action,
			const char *buf, size_t count)
{
	struct cc_device *cc = dev_get_drvdata(device);
	struct cc_plan *plan;
	u8 *specs, *charge, *flags, *input;
	u64 feature, dtt;
	int v[8], n = 0, error = 0;
	unsigned int i, attempt;
	char *copy, *cursor, *token;
	/* Split only decimal fields, bounded count and exact field counts below. */
	if (!count || count > 128 || memchr(buf, '\0', count)) return -EINVAL;
	copy = kstrndup(buf, count, GFP_KERNEL);
	if (!copy) return -ENOMEM;
	cursor = copy;
	while ((token = strsep(&cursor, " \t\n")) != NULL) {
		if (!*token) continue;
		if (n == 8 || kstrtoint(token, 10, &v[n])) { error = -EINVAL; break; }
		n++;
	}
	kfree(copy);
	if (error) return error;
	/* Keep transaction buffers off the small kernel stack. */
	plan = kzalloc(sizeof(*plan) + 4 * 256, GFP_KERNEL);
	if (!plan) return -ENOMEM;
	specs = (u8 *)(plan + 1);
	charge = specs + 256;
	flags = charge + 256;
	input = flags + 256;
	mutex_lock(&cc->lock);
	error = cc_read_locked(cc, 13, 0, specs);
	if (error) goto out;
	if (action == CC_CHARGE) error = cc_read_locked(cc, 4, 30, charge);
	if (action == CC_FLAGS) error = cc_read_locked(cc, 4, 24, flags);
	if (error) goto out;
	if (cc_prepare(action, v, n, specs, charge, flags, plan)) { error = -EINVAL; goto out; }
	if (action == CC_OFFSET || action == CC_POWER) {
		error = cc_call_locked(cc, 0x60, input, NULL, &feature);
		if (error) goto out;
		if ((action == CC_OFFSET && (feature & (1 << 10))) ||
		    (action == CC_POWER && !(feature & 4))) { error = -EOPNOTSUPP; goto out; }
	}
	if (action == CC_POWER && v[0] == 2) {
		/* Preserve firmware DTT selection without importing Windows preferences. */
		error = cc_named_locked(cc, "\\_SB.PC00.LPCB.EC.DTTF", &dtt);
		if (error) goto out;
		if (dtt) plan->request[0].data[0] |= 0x80;
	}
	if (action == CC_CAMERA) {
		error = cc_call_locked(cc, 6, input, NULL, &feature);
		if (error || feature > 1) { if (!error) error = -EOPNOTSUPP; goto out; }
	}
	for (i = 0; i < plan->count; i++) {
		error = cc_call_locked(cc, plan->request[i].function, plan->request[i].data, NULL, NULL);
		if (error) goto out;
		if (action == CC_CURVE && i == 0) {
			error = cc_confirm_mode_locked(cc, 1);
			if (error) goto out;
		}
		/* Verify the upload BEFORE selecting Custom; leave Maximum on failure. */
		if (action == CC_CURVE && i == 1) {
			error = cc_verify_locked(cc, action, v, plan);
			if (error) goto out;
		}
	}
	if (action == CC_CURVE) {
		error = cc_confirm_mode_locked(cc, 6);
	} else {
		for (attempt = 0; attempt < 10; attempt++) {
			error = cc_verify_locked(cc, action, v, plan);
			if (!error || error != -EIO) break;
			msleep(50);
		}
	}
out:
	mutex_unlock(&cc->lock);
	kfree(plan);
	return error ? error : count;
}

#define CC_ATTRIBUTE(name, action) \
static ssize_t name##_show(struct device *dev, struct device_attribute *attr, char *buf) \
{ \
	struct cc_device *cc = dev_get_drvdata(dev); \
	int error; \
	mutex_lock(&cc->lock); \
	error = cc_state_locked(cc, action, buf); \
	mutex_unlock(&cc->lock); \
	return error; \
} \
static ssize_t name##_store(struct device *dev, struct device_attribute *attr, const char *buf, size_t count) \
{ return cc_store(dev, action, buf, count); } \
static DEVICE_ATTR(name, 0644, name##_show, name##_store)

CC_ATTRIBUTE(fan_mode, CC_FAN);
CC_ATTRIBUTE(fan_offset, CC_OFFSET);
CC_ATTRIBUTE(fan_curve, CC_CURVE);
CC_ATTRIBUTE(keyboard_rgb, CC_RGB);
CC_ATTRIBUTE(keyboard_brightness, CC_BRIGHTNESS);
CC_ATTRIBUTE(charge_limits, CC_CHARGE);
CC_ATTRIBUTE(keyboard_flags, CC_FLAGS);
CC_ATTRIBUTE(keyboard_sleep, CC_SLEEP);
CC_ATTRIBUTE(camera, CC_CAMERA);
CC_ATTRIBUTE(power_mode, CC_POWER);
