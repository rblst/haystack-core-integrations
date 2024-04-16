class AmazonBedrockError(Exception):
    """
    Any error generated by the Amazon Bedrock integration.

    This error wraps its source transparently in such a way that its attributes
    can be accessed directly: for example, if the original error has a `message` attribute,
    `AmazonBedrockError.message` will exist and have the expected content.
    """


class AWSConfigurationError(AmazonBedrockError):
    """Exception raised when AWS is not configured correctly"""


class AmazonBedrockConfigurationError(AmazonBedrockError):
    """Exception raised when AmazonBedrock node is not configured correctly"""


class AmazonBedrockInferenceError(AmazonBedrockError):
    """Exception for issues that occur in the Bedrock inference node"""