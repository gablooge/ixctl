try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

import fullctl.service_bridge.devicectl as devicectl
import fullctl.service_bridge.pdbctl as pdbctl
import yaml
from django.core.validators import RegexValidator
from django.utils.translation import ugettext_lazy as _
from django_inet.rest import IPAddressField
from fullctl.django.models.concrete.tasks import TaskLimitError
from fullctl.django.rest.decorators import serializer_registry
from fullctl.django.rest.serializers import (
    ModelSerializer,
    RequireContext,
    SoftRequiredValidator,
)
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.validators import UniqueTogetherValidator

import django_ixctl.models as models
from django_ixctl.peeringdb import import_exchange, import_org

Serializers, register = serializer_registry()


@register
class ImportOrganization(RequireContext, serializers.Serializer):
    pdb_org_id = serializers.IntegerField(required=False)

    required_context = ["instance"]

    ref_tag = "imporg"

    class Meta:
        fields = [
            "pdb_org_id",
        ]

    def validate_pdb_org_id(self, value):
        if not value:
            return 0
        self.pdb_org = pdbctl.Organization().object(value)
        if not self.pdb_org:
            raise ValidationError(_("Unknown peeringdb organization"))
        return self.pdb_org.id

    def save(self):
        instance = self.context.get("instance")
        pdb_org = getattr(self, "pdb_org", None)
        return import_org(pdb_org, instance)


@register
class ImportExchange(RequireContext, serializers.Serializer):
    pdb_ix_id = serializers.IntegerField()

    required_context = ["instance"]

    ref_tag = "impix"

    class Meta:
        fields = [
            "pdb_ix_id",
        ]

    def validate_pdb_ix_id(self, value):
        instance = self.context.get("instance")
        if not value:
            return 0

        try:
            self.pdb_ix = pdbctl.InternetExchange().object(value)
        except KeyError:
            raise ValidationError(_("Unknown peeringdb exchange"))

        qset = models.InternetExchange.objects.filter(
            instance=instance, pdb_id=self.pdb_ix.id
        )

        if qset.exists():
            raise ValidationError(_("You have already imported this exchange"))

        return self.pdb_ix.id

    def validate(self, cleaned_data):
        instance = self.context.get("instance")
        slug = models.InternetExchange.default_slug(self.pdb_ix.name)
        qset = models.InternetExchange.objects.filter(instance=instance, slug=slug)
        if qset.exists():
            raise ValidationError(
                _("You already have an exchange with the identifier `{}`").format(slug)
            )
        return cleaned_data

    def save(self):
        instance = self.context.get("instance")
        ix = import_exchange(self.pdb_ix, instance)
        return ix


@register
class PermissionRequest(ModelSerializer):
    class Meta:
        model = models.PermissionRequest
        fields = ["user", "type", "org"]


@register
class InternetExchange(ModelSerializer):
    slug = serializers.SlugField(required=False)

    class Meta:
        model = models.InternetExchange
        fields = [
            "pdb_id",
            "urlkey",
            "instance",
            "ixf_export_privacy",
            "name",
            "slug",
            "source_of_truth",
            "verified",
        ]

        read_only_fields = [
            "verified",
            "source_of_truth",
        ]

    def validate(self, cleaned_data):
        instance = cleaned_data.get("instance")
        slug = cleaned_data.get("slug")
        if not slug:
            slug = models.InternetExchange.default_slug(cleaned_data["name"])
        print("checking", instance, slug)
        qset = models.InternetExchange.objects.filter(instance=instance, slug=slug)
        if qset.exists():
            raise ValidationError(
                _("You already have an exchange with the identifier `{}`").format(slug)
            )
        cleaned_data["slug"] = slug
        return cleaned_data


@register
class InternetExchangeMember(ModelSerializer):
    ipaddr4 = IPAddressField(
        version=4, allow_blank=True, allow_null=True, required=False, default=None
    )
    ipaddr6 = IPAddressField(
        version=6, allow_blank=True, allow_null=True, required=False, default=None
    )
    macaddr = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
        default=None,
        validators=[RegexValidator(r"(?i)^([0-9a-f]{2}[-:]){5}[0-9a-f]{2}$")],
    )

    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = models.InternetExchangeMember
        fields = [
            "id",
            "pdb_id",
            "ix",
            "ixf_member_type",
            "ixf_state",
            "asn",
            "name",
            "display_name",
            "ipaddr4",
            "ipaddr6",
            "macaddr",
            "as_macro",
            "as_macro_override",
            "is_rs_peer",
            "speed",
            "md5",
            "prefix4",
            "prefix6",
            "port",
        ]
        validators = [
            SoftRequiredValidator(
                fields=("ipaddr4", "ipaddr6"),
                message=_("Input required for IPv4 or IPv6"),
            ),
            UniqueTogetherValidator(
                queryset=models.InternetExchangeMember.objects.all(),
                fields=("ipaddr4", "ix"),
                message="IPv4 address exists already in this exchange",
            ),
            UniqueTogetherValidator(
                queryset=models.InternetExchangeMember.objects.all(),
                fields=("ipaddr6", "ix"),
                message="IPv6 address exists already in this exchange",
            ),
        ]

    def validate_ipaddr4(self, ipaddr4):
        if not ipaddr4:
            return None
        return ipaddr4

    def validate_ipaddr6(self, ipaddr6):
        if not ipaddr6:
            return None
        return ipaddr6

    def validate_macaddr(self, macaddr):
        if not macaddr:
            return None
        return macaddr

    def validate_md5(self, md5):
        if not md5:
            return None
        return md5

    def validate_port(self, port):
        """
        Validates the port to make sure it exists and belongs to the requesting
        organization
        """
        org_instance = self.context.get("instance")

        if not port:
            return port

        # check that port exists and belongs to the requesting organization

        port_object = devicectl.Port().first(
            id=int(port), org_slug=org_instance.org.slug
        )

        if not port_object:
            raise ValidationError(_("Port not found"))

        return port_object.id


@register
class InternetExchangeMemberDetail(ModelSerializer):
    ref_tag = "member_detail"
    port = serializers.SerializerMethodField()

    class Meta(InternetExchangeMember.Meta):
        fields = InternetExchangeMember.Meta.fields + ["port"]

    def get_port(self, member):
        if not member.port:
            return None
        try:
            port = member.port.object.__dict__
            port["device"] = port["device"].__dict__
            return port
        except AttributeError:
            return None


@register
class Routeserver(ModelSerializer):
    router_id = IPAddressField(
        version=4,
    )

    class Meta:
        model = models.Routeserver
        fields = [
            "id",
            "ix",
            "name",
            "display_name",
            "asn",
            "router_id",
            "ars_type",
            "max_as_path_length",
            "no_export_action",
            "rpki_bgp_origin_validation",
            "graceful_shutdown",
            "extra_config",
            "routeserver_config_status",
            "routeserver_config_generated_time",
            "routeserver_config_response",
            "routeserver_config_error",
        ]

    def validate_extra_config(self, value):
        try:
            data = yaml.load(value, Loader=Loader)
        except Exception as exc:
            raise serializers.ValidationError(f"Invalid yaml formatting: {exc}")

        if data and not isinstance(data, dict):
            raise serializers.ValidationError("Config object literal expected")
        return value

    def save(self):
        r = super().save()
        try:
            r.routeserver_config.queue_generate()
        except TaskLimitError:
            pass
        return r


@register
class RouteserverConfig(ModelSerializer):
    class Meta:
        model = models.RouteserverConfig
        fields = [
            "routeserver",
            "generated",
            "body",
        ]


@register
class DefaultExchange(ModelSerializer):
    ref_tag = "default_ix"

    class Meta:
        model = models.OrganizationDefaultExchange
        fields = ["org", "ix"]

    def save(self):
        org = self.validated_data["org"]
        ix = self.validated_data["ix"]

        models.InternetExchange.set_default_exchange_for_org(org, ix)


@register
class PeeringDBRouteserver(serializers.Serializer):
    ref_tag = "pdbrouteserver"

    id = serializers.IntegerField()
    router_id = serializers.SerializerMethodField()
    name = serializers.CharField(read_only=True)
    asn = serializers.IntegerField(read_only=True)

    class Meta:
        fields = ["id", "router_id", "name", "asn"]

    def get_router_id(self, obj):
        return obj.ipaddr4 or ""


@register
class Network(ModelSerializer):
    class Meta:
        model = models.Network
        fields = ["pdb_id", "asn", "name", "display_name"]


@register
class NetworkPresence(InternetExchangeMember):
    org = serializers.SerializerMethodField()
    org_name = serializers.SerializerMethodField()
    access = serializers.SerializerMethodField()
    ref_tag = "presence"

    class Meta(InternetExchangeMember.Meta):
        fields = InternetExchangeMember.Meta.fields + [
            "org",
            "org_name",
            "ix_name",
            "access",
        ]

    @property
    def permrequest(self):
        user = self.context.get("user")
        if not hasattr(self, "_permrequest"):
            self._permrequest = {
                pr.org_id: True
                for pr in models.PermissionRequest.objects.filter(user=user)
            }
        return self._permrequest

    def get_org(self, obj):
        return obj.org.slug

    def get_org_name(self, obj):
        return obj.org.name

    def get_access(self, obj):
        perms = self.context.get("perms")
        if not perms:
            return False

        namespace = self.get_grainy(obj)

        access_u = perms.check(f"{namespace}.?", "u")
        access_r = perms.check(f"{namespace}", "r")

        if access_u:
            return "manage"

        if access_r:
            return "view"

        if self.get_access_pending(obj):
            return "pending"

        return "denied"

    def get_access_pending(self, obj):
        return self.permrequest.get(obj.org.id, False)
