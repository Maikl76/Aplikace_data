from django.apps import AppConfig


class GeneticsConfig(AppConfig):
    name = "apps.genetics"
    verbose_name = "Genetika"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from apps.subjects.models import Consent

        from . import services

        # Odvolaný (nebo smazaný) souhlas s genetikou maže genotypy – ať se
        # odvolá kdekoli: v portálu, v aplikaci i v administraci.
        post_save.connect(services.on_consent_saved, sender=Consent,
                          dispatch_uid="genetics_consent_saved")
        post_delete.connect(services.on_consent_deleted, sender=Consent,
                            dispatch_uid="genetics_consent_deleted")
