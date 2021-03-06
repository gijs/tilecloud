.PHONY: all
all: test pep8 pyflakes docs

.PHONY: clean
clean:
	find tilecloud tiles -name \*.pyc | xargs rm -f
	make -C docs clean

.PHONY: docs
docs:
	make -C docs html

.PHONY: pep8
pep8:
	find examples tilecloud tiles -name \*.py | xargs pep8 --ignore=E501
	pep8 --ignore=E501 tc-*

.PHONY: pyflakes
pyflakes:
	find examples tilecloud tiles -name \*.py | xargs pyflakes
	pyflakes tc-*

.PHONY: test
test:
	python setup.py nosetests
