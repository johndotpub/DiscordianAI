# Minimal makefile for Sphinx API documentation

# You can set these variables from the command line.
SPHINXOPTS   ?= -W
SPHINXBUILD  ?= python -m sphinx
SOURCEDIR     = api
BUILDDIR      = api/_build

.PHONY: help clean html

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  html   to make standalone HTML files"
	@echo "  clean  to remove build artifacts"

html:
	$(SPHINXBUILD) -b html $(SOURCEDIR) $(BUILDDIR) $(SPHINXOPTS)
	@echo "Build finished. Open $(BUILDDIR)/index.html in a browser."

clean:
	rm -rf $(BUILDDIR)