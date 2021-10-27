#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#


from abc import ABC
from typing import (Any, Iterable, List, Mapping, MutableMapping, Optional,
                    Tuple, Union)

import pendulum
import requests
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth.core import HttpAuthenticator
from airbyte_cdk.sources.streams.http.requests_native_auth import \
    Oauth2Authenticator
from requests.auth import AuthBase

from .util import normalize


class LinnworksStream(HttpStream, ABC):
    http_method = "POST"

    @property
    def url_base(self) -> str:
        return self.authenticator.get_server()

    def __init__(self, authenticator: Union[AuthBase, HttpAuthenticator] = None):
        super().__init__(authenticator=authenticator)

        self._authenticator = authenticator

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        return None

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None
    ) -> MutableMapping[str, Any]:
        return {}

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        for record in response.json():
            yield normalize(record)


class StockLocations(LinnworksStream):
    # https://apps.linnworks.net/Api/Method/Inventory-GetStockLocations
    # Response: List<StockLocation>
    # Allows 150 calls per minute
    primary_key = "stock_location_int_id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "/api/Inventory/GetStockLocations"


# Basic incremental stream
class IncrementalLinnworksStream(LinnworksStream, ABC):
    """
    TODO fill in details of this class to implement functionality related to incremental syncs for your connector.
         if you do not need to implement incremental sync for any streams, remove this class.
    """

    # TODO: Fill in to checkpoint stream reads after N records. This prevents re-reading of data if the stream fails for any reason.
    state_checkpoint_interval = None

    @property
    def cursor_field(self) -> str:
        """
        TODO
        Override to return the cursor field used by this stream e.g: an API entity might always use created_at as the cursor field. This is
        usually id or date based. This field's presence tells the framework this in an incremental stream. Required for incremental.

        :return str: The name of the cursor field.
        """
        return []

    def get_updated_state(self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        """
        Override to determine the latest state after reading the latest record. This typically compared the cursor_field from the latest record and
        the current state and picks the 'most' recent cursor. This is how a stream's state is determined. Required for incremental.
        """
        return {}


class Employees(IncrementalLinnworksStream):
    """
    TODO: Change class name to match the table/data source this stream corresponds to.
    """

    # TODO: Fill in the cursor_field. Required.
    cursor_field = "start_date"

    # TODO: Fill in the primary key. Required. This is usually a unique field in the stream, like an ID or a timestamp.
    primary_key = "employee_id"

    def path(self, **kwargs) -> str:
        """
        TODO: Override this method to define the path this stream corresponds to. E.g. if the url is https://example-api.com/v1/employees then this should
        return "single". Required.
        """
        return "employees"

    def stream_slices(self, stream_state: Mapping[str, Any] = None, **kwargs) -> Iterable[Optional[Mapping[str, any]]]:
        """
        TODO: Optionally override this method to define this stream's slices. If slicing is not needed, delete this method.

        Slices control when state is saved. Specifically, state is saved after a slice has been fully read.
        This is useful if the API offers reads by groups or filters, and can be paired with the state object to make reads efficient. See the "concepts"
        section of the docs for more information.

        The function is called before reading any records in a stream. It returns an Iterable of dicts, each containing the
        necessary data to craft a request for a slice. The stream state is usually referenced to determine what slices need to be created.
        This means that data in a slice is usually closely related to a stream's cursor_field and stream_state.

        An HTTP request is made for each returned slice. The same slice can be accessed in the path, request_params and request_header functions to help
        craft that specific request.

        For example, if https://example-api.com/v1/employees offers a date query params that returns data for that particular day, one way to implement
        this would be to consult the stream state object for the last synced date, then return a slice containing each date from the last synced date
        till now. The request_params function would then grab the date from the stream_slice and make it part of the request by injecting it into
        the date query param.
        """
        raise NotImplementedError(
            "Implement stream slices or delete this method!")


class LinnworksAuthenticator(Oauth2Authenticator):
    def __init__(
        self,
        token_refresh_endpoint: str,
        application_id: str,
        application_secret: str,
        token: str,
        token_expiry_date: pendulum.datetime = None,
        access_token_name: str = "Token",
        server_name: str = "Server",
    ):
        super().__init__(
            token_refresh_endpoint,
            application_id,
            application_secret,
            token,
            scopes=None,
            token_expiry_date=token_expiry_date,
            access_token_name=access_token_name,
        )

        self.expires_in = 1800

        self.application_id = application_id
        self.application_secret = application_secret
        self.token = token
        self.server_name = server_name

    def get_auth_header(self) -> Mapping[str, Any]:
        return {"Authorization": self.get_access_token()}

    def get_access_token(self):
        if self.token_has_expired():
            t0 = pendulum.now()
            token, server = self.refresh_access_token()
            self._access_token = token
            self._server = server
            self._token_expiry_date = t0.add(seconds=self.expires_in)

        return self._access_token

    def get_server(self):
        if self.token_has_expired():
            self.get_access_token()

        return self._server

    def get_refresh_request_body(self) -> Mapping[str, Any]:
        payload: MutableMapping[str, Any] = {
            "applicationId": self.application_id,
            "applicationSecret": self.application_secret,
            "token": self.token,
        }

        return payload

    def refresh_access_token(self) -> Tuple[str, int]:
        try:
            response = requests.request(
                method="POST", url=self.token_refresh_endpoint, data=self.get_refresh_request_body())
            response.raise_for_status()
            response_json = response.json()
            return response_json[self.access_token_name], response_json[self.server_name]
        except Exception as e:
            raise Exception(f"Error while refreshing access token: {e}") from e


class SourceLinnworks(AbstractSource):
    def _auth(self, config):
        return LinnworksAuthenticator(
            token_refresh_endpoint="https://api.linnworks.net/api/Auth/AuthorizeByApplication",
            application_id=config["application_id"],
            application_secret=config["application_secret"],
            token=config["token"],
        )

    def check_connection(self, logger, config) -> Tuple[bool, any]:
        try:
            self._auth(config).get_auth_header()
        except Exception as e:
            return None, e

        return True, None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        auth = self._auth(config)
        return [
            StockLocations(authenticator=auth),
            Employees(authenticator=auth)
        ]
