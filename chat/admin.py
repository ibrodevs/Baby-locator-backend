from django.contrib import admin

from .models import Message, Reward, Task

admin.site.register(Message)
admin.site.register(Task)
admin.site.register(Reward)
