# This file is part of Indico.
# Copyright (C) 2002 - 2025 CERN
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see the
# LICENSE file for more details.

import re

from flask import render_template, session

from indico.core import signals
from indico.util.signals import values_from_signal


class Previewer:
    """Base class for file previewers.

    To create a new file prewiewer, subclass this class and register it using
    the `get_file_previewers` signal.
    """

    ALLOWED_CONTENT_TYPE = None
    TEMPLATES_DIR = 'attachments/previewers/'
    TEMPLATE = None

    @classmethod
    def can_preview(cls, attachment_file):
        """
        Check if the content type of the file matches the allowed content
        type of files that the previewer can be used for.
        """
        return cls.ALLOWED_CONTENT_TYPE.search(attachment_file.content_type) is not None

    @classmethod
    def generate_content(cls, attachment):
        """Generate the HTML output of the file preview."""
        return render_template(cls.TEMPLATES_DIR + cls.TEMPLATE, attachment=attachment)


class ImagePreviewer(Previewer):
    ALLOWED_CONTENT_TYPE = re.compile(r'^image/')
    TEMPLATE = 'image_preview.html'


class PDFPreviewer(Previewer):
    ALLOWED_CONTENT_TYPE = re.compile(r'^application/pdf$')
    TEMPLATE = 'iframe_preview.html'

    @classmethod
    def can_preview(cls, attachment_file):
        if not super().can_preview(attachment_file) or not session.user:
            return False
        return session.user.settings.get('use_previewer_pdf', False)


class MarkdownPreviewer(Previewer):
    ALLOWED_CONTENT_TYPE = re.compile(r'^text/markdown$')

    @classmethod
    def generate_content(cls, attachment):
        with attachment.file.open() as f:
            return render_template(cls.TEMPLATES_DIR + 'markdown_preview.html', attachment=attachment,
                                   text=f.read().decode())


class TextPreviewer(Previewer):
    ALLOWED_CONTENT_TYPE = re.compile(r'^text/plain$')

    @classmethod
    def generate_content(cls, attachment):
        with attachment.file.open() as f:
            content = f.read()
            try:
                text = content.decode()  # utf-8
            except UnicodeDecodeError:
                try:
                    text = content.decode('latin1')
                except UnicodeDecodeError:
                    # not sure if there's anything where latin1 decoding fails, but just in
                    # case we decode such a file as utf-8 and replace anything that's invalid
                    text = content.decode(errors='replace')
            return render_template(cls.TEMPLATES_DIR + 'text_preview.html', attachment=attachment, text=text)


def get_file_previewer(attachment_file):
    """
    Return a file previewer for the given attachment file based on the
    file's content type.
    """
    for previewer in get_file_previewers():
        if previewer.can_preview(attachment_file):
            return previewer()


def get_file_previewers():
    return values_from_signal(signals.attachments.get_file_previewers.send())


@signals.attachments.get_file_previewers.connect
def _get_file_previewers(sender, **kwargs):
    yield ImagePreviewer
    yield PDFPreviewer
    yield MarkdownPreviewer
    yield TextPreviewer
