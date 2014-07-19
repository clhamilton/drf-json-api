from rest_framework import relations, renderers, serializers
from rest_framework_json_api import encoders
from django.utils import encoding, six


def convert_resource(resource, request):
    links = {}
    linked = {}
    data = resource.copy()

    fields = fields_from_resource(resource)

    if "id" in fields:
        data["id"] = encoding.force_text(data["id"])

    if "url" in fields:
        data["href"] = data["url"]
        del data["url"]

    for field_name, field in six.iteritems(fields):
        if isinstance(field, relations.HyperlinkedRelatedField):
            data, field_links, field_linked = handle_url_field(data, field, field_name, request)

            links.update(field_links)
            linked.update(field_linked)

        if isinstance(field, serializers.Serializer):
            data, field_links, field_linked = handle_nested_serializer(data, field, field_name, request)

            links.update(field_links)
            linked.update(field_linked)

    return (data, links, linked)


def prepend_links_with_name(links, name):
    changed_links = links.copy()

    for link_name, link_obj in six.iteritems(links):
        prepended_name = "%s.%s" % (name, link_name)
        link_template = "{%s}" % link_name
        prepended_template = "{%s}" % prepended_name

        updated_obj = changed_links[link_name]

        updated_obj["href"] = link_obj["href"].replace(link_template, prepended_template)

        changed_links[prepended_name] = changed_links[link_name]
        del changed_links[link_name]

    return changed_links


def handle_nested_serializer(resource, field, field_name, request):
    links = {}
    linked = {}
    data = resource.copy()

    model = field.opts.model

    resource_type = model_to_resource_type(model)

    if field.many:
        obj_ids = []

        for item in data[field_name]:
            linked_obj, field_links, field_linked = convert_resource(item, request)

            obj_ids.append(linked_obj["id"])

            field_links = prepend_links_with_name(field_links, resource_type)

            nested_fields = fields_from_resource(item)

            if "url" in nested_fields:
                url_field = nested_fields["url"]

                field_links[field_name] = {
                    "href": url_to_template(url_field.view_name, request, field_name),
                    "type": resource_type,
                }

            links.update(field_links)

            if resource_type not in linked:
                linked[resource_type] = []

            linked[resource_type].append(linked_obj)

        if "links" not in data:
            data["links"] = {}

        data["links"][field_name] = obj_ids
        del data[field_name]

    return data, links, linked


def handle_url_field(resource, field, field_name, request):
    links = {}
    linked = {}
    data = resource.copy()

    model = model_from_obj(field)
    resource_type = model_to_resource_type(model)

    links[field_name] = {
        "href": url_to_template(field.view_name, request, field_name),
        "type": resource_type,
    }

    if field_name in data:
        if "links" not in data:
            data["links"] = {}

        data["links"][field_name] = url_to_pk(data[field_name], field)
        del data[field_name]

    return (data, links, linked)


def url_to_pk(url_data, field):
    if field.many:
        obj_list = [field.from_native(url) for url in url_data]
        return [encoding.force_text(obj.pk) for obj in obj_list]

    obj = field.from_native(url_data)
    return encoding.force_text(obj.pk)

def url_to_template(view_name, request, template_name):
    from rest_framework.reverse import reverse

    test_pk = 999999

    test_kwargs = {
        "pk": test_pk,
    }
    test_reverse = reverse(view_name, kwargs=test_kwargs, request=request)

    href = test_reverse.replace(encoding.force_text(test_pk), "{%s}" % template_name)

    return href

def fields_from_resource(resource):
    fields = getattr(resource, "fields", None)

    if fields is not None:
        return fields

    return None


def model_from_obj(obj):
    model = getattr(obj, "model", None)

    if model is not None:
        return model

    queryset = getattr(obj, "queryset", None)

    if queryset is not None:
        return queryset.model

    return None


def model_to_resource_type(model):
    if model is None:
        return "data"

    return encoding.force_text(model._meta.verbose_name_plural)


class JsonApiMixin(object):
    encoder_class = encoders.JSONEncoder

    def render(self, data, accepted_media_type=None, renderer_context=None):
        wrapper = {}

        view = renderer_context.get("view", None)
        request = renderer_context.get("request", None)

        model = model_from_obj(view)
        resource_type = model_to_resource_type(model)

        links = {}
        linked = {}
        item = {}

        if isinstance(data, list):
            links = {}
            linked = {}
            items = []

            for resource in data:
                converted_item, resource_links, resource_linked = \
                    convert_resource(resource, request)

                items.append(converted_item)
                links.update(resource_links)
                linked.update(resource_linked)

            item = items
        else:
            item, links, linked = convert_resource(data, request)

        wrapper[resource_type] = item

        if links:
            links = prepend_links_with_name(links, resource_type)

            wrapper["links"] = links

        if linked:
            wrapper["linked"] = linked

        renderer_context["indent"] = 4

        return super(JsonApiMixin, self).render(
            data=wrapper,
            accepted_media_type=accepted_media_type,
            renderer_context=renderer_context,
        )


class JsonApiRenderer(JsonApiMixin, renderers.JSONRenderer):
    pass
