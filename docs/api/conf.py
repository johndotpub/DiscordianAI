"""Sphinx configuration for DiscordianAI API reference."""

import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

project = "DiscordianAI"
copyright = "2025, johndotpub"
author = "johndotpub"

release = "0.2.9.8"
version = "0.2.9.8"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
]

templates_path = ["_templates"]
exclude_patterns = ["_build"]

html_theme = "furo"
html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#5865F2",
        "color-brand-content": "#5865F2",
    },
    "dark_css_variables": {
        "color-brand-primary": "#8B9AFF",
        "color-brand-content": "#8B9AFF",
    },
}

html_title = "DiscordianAI API Reference"
html_short_title = "DiscordianAI"

autosummary_generate = False
autosummary_imported_members = True

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}

autodoc_typehints = "description"
autodoc_typehints_format = "short"
autodoc_preserve_defaults = True

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "discord": ("https://discordpy.readthedocs.io/en/stable", None),
}
