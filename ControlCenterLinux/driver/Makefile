
obj-m += acer_al15g52.o

KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all clean

all:
	KDIR="$(KDIR)" bash "$(CURDIR)/build-module.sh"

clean:
	rm -f -- "$(CURDIR)/acer_al15g52.ko"
