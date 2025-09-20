import os
from typing import Dict, Any, Optional, List

class BrokerBase:
    """
    An abstract base class for broker implementations.

    This class defines the common interface that all broker-specific classes
    should adhere to. It provides a structure for authentication and basic
    introspection of available methods. Subclasses must implement the
    `authenticate` method.

    Attributes:
        authenticated (bool): True if the broker session is authenticated.
        access_token (str or None): The access token obtained after successful
            authentication.
        env (os._Environ): A reference to the environment variables.
    """
    def __init__(self):
        """Initializes the BrokerBase."""
        self.authenticated = False
        self.access_token = None
        self.env = os.environ

    def authenticate(self) -> Optional[str]:
        """
        Authenticates with the broker's API.

        This method must be implemented by subclasses to handle the specific
        authentication flow of the target broker (e.g., OAuth2, TOTP).

        Raises:
            NotImplementedError: If the subclass does not implement this method.

        Returns:
            An access token string if authentication is successful, otherwise
            None. The exact return type may vary by implementation, but often
            includes the access token and other session data.
        """
        raise NotImplementedError("Subclasses must implement authenticate()")

    def list_functions(self) -> List[str]:
        """
        Lists the available public methods in the broker implementation.

        This method introspects the subclass instance and returns a sorted list
        of its public method names, excluding methods from this base class and
        any private methods (those starting with an underscore).

        Returns:
            A sorted list of public method names available in the subclass.
        """
        base_methods = set(dir(BrokerBase))
        all_methods = set(dir(self))
        public_methods = [m for m in all_methods - base_methods if not m.startswith('_')]
        return sorted(public_methods) 