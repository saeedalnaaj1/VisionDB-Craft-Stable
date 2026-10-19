"""Core lifecycle hooks: Stable does not import or initialize model services."""
class CoreFeatures:
    def _initialize_features(self):
        pass

    def _feature_job_snapshot(self):
        return {}
