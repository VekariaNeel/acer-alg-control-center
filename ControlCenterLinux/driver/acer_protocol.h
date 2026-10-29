/* SPDX-License-Identifier: GPL-2.0-only */
/* Pure encoding/validation shared by the kernel bridge and offline C checks. */
#ifndef ACER_AL15G52_PROTOCOL_H
#define ACER_AL15G52_PROTOCOL_H
#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/string.h>
#else
#include <stddef.h>
typedef unsigned char u8;
extern void *memset(void *, int, size_t);
extern void *memcpy(void *, const void *, size_t);
#endif

enum cc_action { CC_FAN, CC_OFFSET, CC_CURVE, CC_RGB, CC_BRIGHTNESS,
	CC_CHARGE, CC_FLAGS, CC_SLEEP, CC_CAMERA, CC_POWER };
struct cc_request { unsigned int function; u8 data[256]; };
struct cc_plan { unsigned int count; struct cc_request request[4]; };

static inline unsigned int cc_round(unsigned int num, unsigned int den)
{
	unsigned int q = num / den, r = num % den;
	return q + (r * 2 > den || (r * 2 == den && (q & 1)));
}
static inline unsigned int cc_scale(unsigned int percent)
{
	return cc_round(percent * 255, 100);
}
static inline int cc_fan_mode(unsigned int raw)
{
	return raw == 2 ? 0 : raw == 16 ? 1 : raw == 4 ? 6 : -1;
}
static inline void cc_integer(struct cc_request *r, unsigned int function,
			     unsigned int sub, unsigned int value)
{
	r->function = function;
	r->data[0] = value;
	r->data[1] = value >> 8;
	r->data[2] = value >> 16;
	r->data[3] = sub;
}

/* Return -1 before creating ANY firmware transaction for an invalid request.
 * All fields are signed ints to reject negative/overflowed UI or sysfs inputs.
 * Only editable middle knots are accepted. Firmware endpoints are preserved.
 */
static inline int cc_prepare(enum cc_action action, const int *v, unsigned int n,
			     const u8 *specs, const u8 *charge, const u8 *flags,
			     struct cc_plan *plan)
{
	unsigned int i, fan, t[4], d[4], p, slope, den, num;
	int blue;
	memset(plan, 0, sizeof(*plan));
	if (specs[12] != 2 || specs[15] != 6)
		return -1;
	for (i = 0; i < n; i++)
		if (v[i] < 0 || v[i] > 7199)
			return -1;
	switch (action) {
	case CC_FAN:
		if (n != 1 || (v[0] != 0 && v[0] != 1)) return -1;
		cc_integer(&plan->request[0], 0x79, 1, v[0]);
		break;
	case CC_OFFSET:
		if (n != 1 || v[0] > 100 || cc_fan_mode(specs[14]) != 0) return -1;
		cc_integer(&plan->request[0], 0x79, 14, cc_scale(v[0]));
		break;
	case CC_CURVE:
		if (n != 8 || (specs[43] & 2)) return -1;
		/* Upload and readback are performed while Maximum is selected. */
		cc_integer(&plan->request[0], 0x79, 1, 1);
		plan->request[1].function = 14;
		for (fan = 0; fan < 2; fan++) {
			p = 16 + fan * 8;
			t[0] = specs[p]; d[0] = specs[p + 1];
			t[1] = v[fan * 4]; d[1] = cc_scale(v[fan * 4 + 1]);
			t[2] = v[fan * 4 + 2]; d[2] = cc_scale(v[fan * 4 + 3]);
			t[3] = specs[p + 6]; d[3] = specs[p + 7];
			if (t[0] < 20 || t[3] < 90 || t[3] > 100 || d[3] != 255 ||
			    v[fan * 4 + 1] > 100 || v[fan * 4 + 3] > 100) return -1;
			for (i = 1; i < 4; i++)
				if (t[i] <= t[i - 1] || t[i] > 100 || d[i] <= d[i - 1]) return -1;
			p = 2 + fan * 4;
			plan->request[1].data[p] = t[1];
			plan->request[1].data[p + 1] = d[1];
			plan->request[1].data[p + 2] = t[2];
			plan->request[1].data[p + 3] = d[2];
			for (i = 0; i < 3; i++) {
				/* Original CC40 uses percent-space slopes, rounded to nearest.
				 * Use integer rational arithmetic, no kernel floating point. */
				num = ((i == 0 ? v[fan * 4 + 1] : i == 1 ? v[fan * 4 + 3] : 100)
				       - (i == 0 ? (specs[16 + fan * 8 + 1] * 100 + 127) / 255
				          : i == 1 ? v[fan * 4 + 1] : v[fan * 4 + 3])) * 408;
				den = (t[i + 1] - t[i]) * 10;
				slope = cc_round(num, den);
				p = 14 + fan * 6 + i * 2;
				plan->request[1].data[p] = slope >> 8;
				plan->request[1].data[p + 1] = slope;
			}
		}
		cc_integer(&plan->request[2], 0x79, 1, 6);
		plan->count = 3;
		return 0;
	case CC_RGB:
		if (n != 3 || v[0] > 255 || v[1] > 255 || v[2] > 255) return -1;
		blue = v[2];
		if (v[0] == 0 && ((v[1] == 254 && blue == 129) || (v[1] == 255 && blue == 127))) blue = 70;
		for (i = 0; i < 3; i++)
			cc_integer(&plan->request[i], 0x67, 240 + i,
				   (blue / 2 << 16) | (v[0] / 2 << 8) | v[1] / 2);
		plan->count = 3;
		return 0;
	case CC_BRIGHTNESS:
		if (n != 1 || v[0] > 4) return -1;
		cc_integer(&plan->request[0], 0x67, 244, v[0] ? 48 * v[0] - 1 : 0);
		break;
	case CC_CHARGE:
		if (n != 3 || v[0] > 1 || v[1] >= v[2] || v[2] > 100 ||
		    charge[0] > 1 || charge[1] >= charge[2] || charge[2] > 100) return -1;
		if (!v[0]) {
			if (v[1] != 95 || v[2] != 100) return -1;
		} else {
			int start = 0, stop = 0;
			for (i = 16; i < 32; i++) if (charge[i] && charge[i] == v[1]) start = 1;
			for (i = 32; i < 48; i++) if (charge[i] && charge[i] == v[2]) stop = 1;
			if (!start || !stop) return -1;
		}
		plan->request[0].function = 4;
		plan->request[0].data[0] = 31;
		for (i = 0; i < 3; i++) plan->request[0].data[i + 1] = v[i];
		break;
	case CC_FLAGS:
		/* One flag per transaction. Preserve all other bytes from a fresh getter. */
		if (n != 2 || v[0] > 2 || v[1] > 1) return -1;
		for (i = 0; i < 3; i++) if (flags[i] < 1 || flags[i] > 2) return -1;
		for (i = 3; i < 5; i++) if (flags[i] > 2) return -1;
		plan->request[0].function = 4;
		plan->request[0].data[0] = 25;
		memcpy(plan->request[0].data + 1, flags, 5);
		plan->request[0].data[v[0] + 1] = (v[1] ^ (v[0] == 1)) ? 1 : 2;
		break;
	case CC_SLEEP:
		if (n != 1 || (v[0] && v[0] < 5)) return -1;
		cc_integer(&plan->request[0], 0x79, 24, v[0] ? (v[0] << 8) | 255 : 0);
		break;
	case CC_CAMERA:
		if (n != 1 || v[0] > 1) return -1;
		cc_integer(&plan->request[0], 34, 0, v[0]);
		break;
	case CC_POWER:
		if (n != 1 || v[0] > 3) return -1;
		cc_integer(&plan->request[0], 0x79, 25, v[0]);
		break;
	default: return -1;
	}
	plan->count = 1;
	return 0;
}
#endif
