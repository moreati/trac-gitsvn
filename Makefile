.PHONY: all
all:

.PHONY: clean
clean:
	find -name \*.py[co] | xargs -d"\n" --no-run-if-empty rm -f
	rm -rf .figleaf* html

.PHONY: test unit-test functional-test
test: unit-test functional-test

unit-test: Trac.egg-info
	PYTHONPATH=$$PWD:$$PYTHONPATH ./trac/test.py --skip-functional-tests

functional-test: Trac.egg-info
	PYTHONPATH=$$PWD:$$PYTHONPATH python trac/tests/functional/__init__.py -v

.PHONY: coverage
coverage: html/index.html

html/index.html: .figleaf.functional .figleaf.unittests
	figleaf2html --exclude-patterns=trac/tests/figleaf-exclude .figleaf.functional .figleaf.unittests

.figleaf.functional: Trac.egg-info
	PYTHONPATH=$$PWD:$$PYTHONPATH FIGLEAF=figleaf python trac/tests/functional/__init__.py -v
	mv .figleaf .figleaf.functional

.figleaf.unittests: Trac.egg-info
	rm -f .figleaf .figleaf.unittests
	PYTHONPATH=$$PWD:$$PYTHONPATH figleaf ./trac/test.py --skip-functional-tests
	mv .figleaf .figleaf.unittests

Trac.egg-info:
	python setup.py egg_info