import os
from datetime import datetime
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.db.models.base import ModelBase
from django.utils.translation import ugettext_lazy as _

from imagekit import specs
from imagekit.lib import *
from imagekit.options import Options
from imagekit.utils import img_to_fobj


class IKModelBase(ModelBase):
    def __init__(cls, name, bases, attrs):
        parents = [b for b in bases if isinstance(b, IKModelBase)]
        if not parents:
            return
        user_opts = getattr(cls, 'IKConfig', None)
        opts = Options(user_opts)
        try:
            module = __import__(opts.spec_module,  {}, {}, [''])
        except ImportError:
            raise ImportError('Unable to load imagekit config module: %s' % \
                opts.spec_module)    
        for spec in [spec for spec in module.__dict__.values() \
                     if isinstance(spec, type) \
                     and issubclass(spec, specs.ImageSpec) \
                     and spec != specs.ImageSpec]:
            setattr(cls, spec.name(), specs.Descriptor(spec))
            opts.specs.append(spec)
        setattr(cls, '_ik', opts)


class IKModel(models.Model):
    """ Abstract base class implementing all core ImageKit functionality
    
    Subclasses of IKModel can override the inner IKConfig class to customize
    storage locations and other options.
    
    """
    __metaclass__ = IKModelBase

    class Meta:
        abstract = True
        
    class IKConfig:
        pass
        
    def admin_thumbnail_view(self):
        prop = getattr(self, self._ik.admin_thumbnail_spec, None)
        if prop is None:
            return 'An "%s" image spec has not been defined.' % \
              self._ik.admin_thumbnail_spec
        else:
            if hasattr(self, 'get_absolute_url'):
                return u'<a href="%s"><img src="%s"></a>' % \
                    (self.get_absolute_url(), prop.url)
            else:
                return u'<a href="%s"><img src="%s"></a>' % \
                    (self._imgfield.url, prop.url)
    admin_thumbnail_view.short_description = _('Thumbnail')
    admin_thumbnail_view.allow_tags = True
    
    @property
    def _imgfield(self):
        return getattr(self, self._ik.image_field)

    def _clear_cache(self):
        for spec in self._ik.specs:
            prop = getattr(self, spec.name())
            prop._delete()

    def _pre_cache(self):
        for spec in self._ik.specs:
            if spec.pre_cache:
                prop = getattr(self, spec.name())
                prop._create()

    def save(self, clear_cache=True, *args, **kwargs):
        is_new_object = self._get_pk_val is None
        super(IKModel, self).save(*args, **kwargs)
        if is_new_object:
            clear_cache = False
            spec = self._ik.preprocessor_spec
            if spec is not None:
                newfile = self._imgfield.storage.open(str(self._imgfield))
                img = Image.open(newfile)
                img = spec.process(img, None)
                format = img.format or 'JPEG'
                if format != 'JPEG':
                    imgfile = img_to_fobj(img, format)
                else:
                    imgfile = img_to_fobj(img, format,
                                          quality=int(spec.quality),
                                          optimize=True)
                content = ContentFile(imgfile.read())
                newfile.close()
                name = str(self._imgfield)
                self._imgfield.storage.delete(name)
                self._imgfield.storage.save(name, content)
        if clear_cache:
            self._clear_cache()
            self._pre_cache()

    def delete(self):
        assert self._get_pk_val() is not None, "%s object can't be deleted because its %s attribute is set to None." % (self._meta.object_name, self._meta.pk.attname)
        self._clear_cache()
        models.Model.delete(self)