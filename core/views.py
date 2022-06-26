import datetime
import math
from django.conf import settings
from django.shortcuts import render
from django.contrib.auth import get_user_model, authenticate
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST
from rest_framework.views import APIView
from .image_detection import detect_faces
from .models import TrackedRequest, Payment
from .permissions import IsMember
from .serializers import (
    ChangeEmailSerializer,
    ChangePasswordSerializer,
    FileSerializer,
    TokenSerializer,
    SubscribeSerializer
)
import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

User = get_user_model()


def get_user_from_token(request):
    key = request.META.get("HTTP_AUTHORIZATION").split(' ')[
        1]  # 2nd element = actual token
    token = Token.objects.get(key=key)
    user = User.objects.get(id=token.user_id)
    return user


class FileUploadView(APIView):
    permission_classes = (AllowAny, )
    throttle_scope = 'demo'  # prevent spam on file upload endpoint

    def post(self, request, *args, **kwargs):

        # limit the content length to 5MB
        content_length = request.META.get('CONTENT_LENGTH')  # bytes

        if int(content_length) > 5000000:
            return Response({"message": "Image size is greater than 5MB"}, status=HTTP_400_BAD_REQUEST)

        file_serializer = FileSerializer(data=request.data)
        if file_serializer.is_valid():
            file_serializer.save()  # save the image into media dir
            image_path = file_serializer.data.get('file')
            recognition = detect_faces(image_path)
        return Response(recognition, status=HTTP_200_OK)


class UserEmailView(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        obj = {'email': user.email}
        return Response(obj)


class ChangeEmailView(APIView):
    permission_classes = (IsAuthenticated, )

    def post(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        email_serializer = ChangeEmailSerializer(data=request.data)
        if email_serializer.is_valid():
            print(email_serializer.data)
            email = email_serializer.data.get('email')
            confirm_email = email_serializer.data.get('confirm_email')
            if email == confirm_email:
                user.email = email
                user.save()

                return Response({"email": email}, status=HTTP_200_OK)
            return Response({"message": "The emails did not match"}, status=HTTP_400_BAD_REQUEST)
        return Response({"message": "We did not receive the correct data"}, status=HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    permission_classes = (IsAuthenticated, )

    def post(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        password_serializer = ChangePasswordSerializer(data=request.data)
        if password_serializer.is_valid():
            password = password_serializer.data.get('password')
            confirm_password = password_serializer.data.get('confirm_password')
            current_password = password_serializer.data.get('current_password')

            auth_user = authenticate(
                username=user.username,
                password=current_password
            )
            # authentifcate the user above and check if auth user is valid below
            if auth_user is not None:
                if password == confirm_password:
                    # set password
                    auth_user.set_password(password)
                    auth_user.save
                    return Response(status=HTTP_200_OK)
                else:
                    return Response({"message": "The passwords did not match"}, status=HTTP_400_BAD_REQUEST)
            return Response({"message": "Incorrect user details"}, status=HTTP_400_BAD_REQUEST)
        return Response({"message": "We did not receive the correct data"}, status=HTTP_400_BAD_REQUEST)


class UserDetailsView(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        membership = user.membership
        today = datetime.datetime.now()
        # 1st day of the current month
        month_start = datetime.date(today.year, today.month, 1)
        tracked_request_count = TrackedRequest.objects \
            .filter(user=user, timestamp__gte=month_start) \
            .count()
        amount_due = 0
        if user.is_member:
            amount_due = stripe.Invoice.upcoming(
                customer=user.stripe_customer_id)['amount_due'] / 100  # because amount in cents
            print(amount_due)
        obj = {
            'membershipType': membership.get_type_display(),
            'free_trial_end_date': membership.end_date,
            'next_billing_date': membership.end_date,
            'api_request_count': tracked_request_count,
            'amount_due': amount_due
        }
        return Response(obj)


class SubscribeView(APIView):
    permission_classes = (IsAuthenticated, )

    def post(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        # get user membership
        membership = user.membership

        try:
            # get stripe customer
            customer = stripe.Customer.retrieve(user.stripe_customer_id)
            serializer = SubscribeSerializer(data=request.data)
            # serializer post data -> stripeToken
            if serializer.is_valid():

                # get stripeToken from the serializer data
                stripe_token = serializer.data.get('stripeToken')

                # create stipe subcription
                subscription = stripe.Subscription.create(
                    customer=customer.id,
                    items=[{"plan": settings.STRIPE_PLAN_ID}]
                )
                # update membership
                membership.stripe_subscription_id = subscription.id
                membership.stripe_subscription_item_id = subscription['items']['data'][0]['id']
                membership.type = 'M'  # now a member
                membership.start_date = datetime.datetime.now()
                membership.end_date = datetime.datetime.fromtimestamp(
                    subscription.current_period_end
                )
                membership.save()
                # update user
                user.is_member = True
                user.on_free_trial = False
                user.save()

                # create payment
                payment = Payment()
                payment.amount = subscription.plan.amount / 100
                payment.user = user
                payment.save()

                return Response({'message': 'Success!'}, status=HTTP_200_OK)

            else:
                return Response({'message': 'Incorrect data was received.'}, status=HTTP_400_BAD_REQUEST)

        except stripe.error.CardError as e:
            return Response({'message': 'Your card has been declined'}, status=HTTP_400_BAD_REQUEST)
        except stripe.error.StripeError as e:
            return Response({'message': 'There was an error. You have not been billed. If this persists please contact support'}, status=HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'message': 'We apologize for the error. We have been informed and working on the issue.'}, status=HTTP_400_BAD_REQUEST)


class CancelSubscription(APIView):
    permission_classes = (IsMember, )

    def post(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        membership = user.membership

        # update stripe subscription (cancelling)
        try:

            sub = stripe.Subscription.retrieve(
                membership.stripe_subscription_id)
            sub.delete()
        except Exception as e:
            return Response({'message': 'We apologize for the error. We have been informed and working on the issue.'}, status=HTTP_400_BAD_REQUEST)

        # update user model
        user.is_member = False
        user.save()
        # update membership
        membership.type = "N"  # Not member
        membership.save()

        return Response({'message': 'Your subscription has been cancelled.'}, status=HTTP_200_OK)


class ImageRecognitionView(APIView):
    permission_classes = (IsMember, )  # we need to check if user is member

    def post(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        membership = user.membership
        file_serializer = FileSerializer(data=request.data)

        usage_record_id = None
        if user.is_member and not user.on_free_trial:
            usage_record = stripe.UsageRecord.create(  # https://stripe.com/docs/api?lang=python
                quantity=1,
                # stripe prefers no decimals
                timestamp=math.floor(datetime.datetime.now().timestamp()),
                subscription_item=membership.stripe_subscription_item_id
            )
            usage_record_id = usage_record.id

        # keep track of the requests a user makes
        tracked_request = TrackedRequest()
        tracked_request.user = user
        tracked_request.usage_record_id = usage_record_id
        # check how to do this with META later
        tracked_request.endpoint = '/api/image-recognition/'
        tracked_request.save()

        # limit the content length to 5MB
        content_length = request.META.get('CONTENT_LENGTH')  # bytes

        if int(content_length) > 5000000:
            return Response({"message": "Image size is greater than 5MB"}, status=HTTP_400_BAD_REQUEST)

        if file_serializer.is_valid():
            file_serializer.save()  # save the image into media dir
            image_path = file_serializer.data.get('file')  # get the file
            recognition = detect_faces(image_path)  # detect the faces from it
            return Response(recognition, status=HTTP_200_OK)
        return Response({"Received incorrect data"}, status=HTTP_400_BAD_REQUEST)


class APIKeyView(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, *args, **kwargs):
        user = get_user_from_token(request)
        token_qs = Token.objecs.filter(user=user)  # token queryset
        if token_qs.exists():
            token_serializer = TokenSerializer(token_qs, many=True)
            try:
                return Response(token_serializer.data, status=HTTP_200_OK)
            except:
                return Response({"message": "Did not receive correct data"}, status=HTTP_400_BAD_REQUEST)
        return Response({"message": "User does not exist"}, status=HTTP_400_BAD_REQUEST)
