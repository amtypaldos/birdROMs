from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Invite
from .services import READONLY, ROLE_GROUPS, user_role


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def validate(self, attrs):
        # Apply the project's AUTH_PASSWORD_VALIDATORS (common/numeric/similar-to-username).
        candidate = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def validate_username(self, value):
        value = value.strip()
        try:
            User._meta.get_field("username").run_validators(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        # Apply the project's AUTH_PASSWORD_VALIDATORS (length/common/numeric/similar-to-username).
        candidate = User(username=attrs["username"], email=attrs.get("email", ""))
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


class InviteCreateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=list(ROLE_GROUPS), default=READONLY)
    expires_in_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    label = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class InviteSerializer(serializers.ModelSerializer):
    """What admins see of an invite. Never the token or its digest."""

    status = serializers.SerializerMethodField()
    used_by = serializers.SlugRelatedField(slug_field="username", read_only=True)
    created_by = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = Invite
        fields = ["id", "label", "role", "status", "created_at", "expires_at", "used_at", "used_by", "created_by"]

    def get_status(self, invite):
        return invite.status()


class MeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "role"]

    def get_role(self, user):
        return user_role(user)
