from django.db import models


class ReviewManager(models.Manager):
    pass


class User(models.Model):
    objects = ReviewManager()

    id = models.BigIntegerField(primary_key=True)
    username = models.CharField(max_length=256)


class Group(models.Model):
    objects = ReviewManager()

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=256)
    admin = models.ForeignKey(User, on_delete=models.CASCADE)


class Review(models.Model):
    objects = ReviewManager()
    
    id = models.BigIntegerField(primary_key=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    from_user = models.ForeignKey(User, related_name="from_user", on_delete=models.CASCADE)
    to_user = models.ForeignKey(User, related_name="to_user", on_delete=models.CASCADE)

    description = models.TextField()
    karma = models.IntegerField()

    created_at = models.DateField(auto_now_add=True)
    updated_at = models.DateField(auto_now=True)

    class Meta:
        ordering = ['group']
