from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models.signals import post_save
from django.conf import settings
from django.utils import timezone
import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

MEMBERSHIP_CHOICES = (
    ('F', 'free_trial'),
    ('M', 'member'),
    ('N', 'not_member')
)


class File(models.Model):
    file = models.ImageField()

    def __str__(self):
        return self.file.name


class User(AbstractUser):
    is_member = models.BooleanField(default=False)
    on_free_trial = models.NullBooleanField(default=True)
    stripe_customer_id = models.CharField(max_length=40)


class Membership(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    type = models.CharField(max_length=1, choices=MEMBERSHIP_CHOICES)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    stripe_subscription_id = models.CharField(
        max_length=40, blank=True, null=True)
    stripe_subscription_item_id = models.CharField(
        max_length=40, blank=True, null=True)

    def __str__(self):
        return self.user.username


class Payment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    amount = models.FloatField()

    def __str__(self):
        return self.user.username


class TrackedRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    endpoint = models.CharField(max_length=50)
    timestamp = models.DateTimeField(auto_now_add=True)
    usage_record_id = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.user.username


def post_save_user_receiver(sender, instance, created, *args, **kwargs):
    if created:  # if being saved and being created we want to create customer and membership
        import datetime
        customer = stripe.Customer.create(email=instance.email)
        instance.stripe_customer_id = customer.id
        instance.save()

        membership = Membership.objects.get_or_create(
            user=instance,
            type='F',
            start_date=timezone.now(),
            end_date=timezone.now() + datetime.timedelta(days=14)  # free subscription time
        )


post_save.connect(post_save_user_receiver, sender=User)
