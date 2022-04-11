PACKAGE := drbd-test

prefix := /usr
exec_prefix := $(prefix)
bindir := $(exec_prefix)/bin
libdir := $(exec_prefix)/lib
datarootdir := $(prefix)/share
datadir := $(datarootdir)
mandir := $(datarootdir)/man
docdir := $(datarootdir)/doc/$(PACKAGE)
#localstatedir := ${prefix}/var
localstatedir := /var

# DESTDIR :=

INSTALL := install

DRBD_TEST_DATA := $(datadir)/$(PACKAGE)
DRBD_TEST_VAR := $(localstatedir)/lib/$(PACKAGE)

data_scripts := \
	disable-faults \
	enable-faults \
	install-config \
	data_generator.py \
	misaligned_bio.py \
	stress-al.py \
	unusual_bios.py \


tarball := $(PACKAGE)-target.tgz

all: $(data_scripts)

$(data_scripts): %: %.in
	@echo "$< -> $@"
	@sed \
		-e 's:@''DRBD_TEST_DATA@:$(DRBD_TEST_DATA):g' \
		-e 's:@''DRBD_TEST_VAR@:$(DRBD_TEST_VAR):g' \
		< $< > $@.tmp
	@test \! -x $< || chmod +x $@.tmp
	@mv $@.tmp $@

install:
	$(INSTALL) -d $(DESTDIR)$(DRBD_TEST_VAR)
	$(INSTALL) -d $(DESTDIR)$(DRBD_TEST_DATA)
	$(INSTALL) -m 755 $(data_scripts) $(DESTDIR)$(DRBD_TEST_DATA)

uninstall:
	rm -f $(patsubst %,$(DESTDIR)$(DRBD_TEST_DATA)/%,$(data_scripts))
	rmdir $(DESTDIR)$(DRBD_TEST_VAR) 2> /dev/null || :
	rmdir $(DESTDIR)$(DRBD_TEST_DATA) 2> /dev/null || :

$(tarball): $(data_scripts) Makefile
	tar -czf $(tarball) $^

tar: $(tarball)

clean:
	rm -f $(data_scripts) $(tarball)
