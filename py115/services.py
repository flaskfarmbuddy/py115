__author__ = 'deadblue'

import os
import os.path
import typing

from py115._internal.api import offline, file, dir, space, upload
from py115._internal.protocol.client import Client

from py115.types import ClearFlag, Task, File, DownloadTicket, UploadTicket


class OfflineService:
    """Offline task manager."""

    _client: Client = None
    _app_ver: str = None
    _user_id: str = None

    @classmethod
    def _create(cls, client: Client, app_ver: str, user_id: str):
        s = cls()
        s._client = client
        s._app_ver = app_ver
        s._user_id = user_id
        return s

    def list(self) -> typing.Generator[Task, None, None]:
        """Get all tasks.

        Yields:
            py115.types.Task: Task object
        """
        spec = offline.ListApi()
        while True:
            result = self._client.execute_api(spec)
            for t in result['tasks']:
                yield Task(t)
            page, page_count = result['page'], result['page_count']
            if page < page_count:
                spec.set_page(page + 1)
            else:
                break

    def add_url(self, *urls: str) -> typing.Iterable[Task]:
        """Create task(s) from download URL.

        Args:
            *urls (str): Download URL, can be a http/ftp/ed2k/magnet link.

        Return:
            Iterable[py115.types.Task]: Task list for the download URLs.
        """
        if len(urls) == 0:
            return []
        add_results = self._client.execute_api(offline.AddUrlsApi(
            self._app_ver, self._user_id, urls
        ))
        return [Task(r) for r in add_results]

    def delete(self, *task_ids: str):
        """Delete task(s).

        Args:
            *task_ids (str): The ID of tasks you wants to delete.
        """
        if len(task_ids) == 0:
            return
        self._client.execute_api(offline.DeleteApi(task_ids))

    def clear(self, flag: ClearFlag = ClearFlag.Done):
        """Clear tasks.
        
        Args:
            flag (py115.types.ClearFlag): Tasks that matches this flag will be delete.
        """
        self._client.execute_api(offline.ClearApi(flag.value))


class StorageService:
    """Cloud file/directory manager.
    """

    _client: Client = None
    _upload_helper: upload.Helper = None

    @classmethod
    def _create(cls, client: Client, uh: upload.Helper):
        s = cls()
        s._client = client
        s._upload_helper = uh
        return s

    def space(self) -> typing.Tuple[int, int]:
        """
        Get total size and used size of the storage.

        Returns:
            Tuple[int, int]: Total size and used size in byte.
        """
        result = self._client.execute_api(space.GetApi())
        if result is not None:
            total = int(result['all_total']['size'])
            used = int(result['all_use']['size'])
            return (total, used)
        else:
            return (0, 0)

    def list(self, dir_id: str = '0') -> typing.Generator[File, None, None]:
        """Get files under a directory.

        Args:
            dir_id (str): Directory ID to list, default is "0" which means root directory.

        Yields:
            py115.types.File: File object under the directory.
        """
        spec = file.ListApi(dir_id)
        while True:
            result = self._client.execute_api(spec)
            for f in result['files']:
                yield File(f)
            next_offset = result['offset'] + len(result['files'])
            if next_offset >= result['count']:
                break
            else:
                spec.set_offset(next_offset)

    def move(self, target_dir_id: str, *file_ids: str):
        """Move files to a directory.

        Args:
            target_dir_id (str): ID of target directory where to move files.
            *file_ids (str): ID of files to be moved.
        """
        if len(file_ids) == 0:
            return
        self._client.execute_api(file.MoveApi(target_dir_id, file_ids))

    def rename(self, file_id: str, new_name: str):
        """Rename file.
        
        Args:
            file_id (str): ID of file to be renamed.
            new_name (str): New name for the file.
        """
        self._client.execute_api(file.RenameApi(file_id, new_name))

    def delete(self, *file_ids: str):
        """Delete files.

        Args:
            *file_ids (str): ID of files to be deleted.
        """
        if len(file_ids) == 0:
            return
        self._client.execute_api(file.DeleteApi(file_ids))

    def make_dir(self, parent_id: str, name: str) -> File:
        """Make new directory under a directory.
        
        Args:
            parent_id (str): ID of parent directory where to make new directory.
            name (str): Name for the new directory.
        
        Return:
            py115.types.File: File object of the created directory.
        """
        result = self._client.execute_api(dir.AddApi(parent_id, name))
        result['pid'] = parent_id
        return File(result)

    def request_download(self, pickcode: str) -> DownloadTicket:
        """Download file from cloud storage.

        Args:
            pickcode (str): Pick code of file.

        Returns:
            py115.types.DownloadTicket: A ticket contains all required fields to 
            download file from cloud.
        """
        result = self._client.execute_api(file.DownloadApi(pickcode))
        if result is None or 'url' not in result:
            return None
        # Required headers for downloading
        cookies = self._client.export_cookies(url=result['url'])
        headers = {
            'User-Agent': self._client.user_agent,
            'Cookie': '; '.join([
                f'{k}={v}' for k, v in cookies.items()
            ])
        }
        return DownloadTicket._create(result, headers)

    def request_upload(self, dir_id: str, file_path: str) -> UploadTicket:
        """Upload local file to cloud storage.

        Args:
            dir_id (str): ID of directory where to store the file.
            file_path (str): Path of the local file.
        
        Return:
            py115.types.UploadTicket: A ticket contains all required fields to
            upload file to cloud, should be used with aliyun-oss-python-sdk.
        """
        if not os.path.exists(file_path):
            return None
        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as file_io:
            return self.request_upload_data(dir_id, file_name, file_io)

    def request_upload_data(
            self, 
            dir_id: str, 
            save_name: str, 
            data_io: typing.BinaryIO, 
        ) -> UploadTicket:
        """Upload data as a file to cloud storage.

        Args:
            dir_id (str): ID of directory where to store the file.
            save_name (str): File name to be saved.
            data_io (BinaryIO): IO stream of data.

        Return:
            py115.types.UploadTicket: A ticket contains all required fields to
            upload file to cloud, should be used with aliyun-oss-python-sdk.
        """
        if not (data_io.readable() and data_io.seekable()):
            return None
        init_result = self._client.execute_api(upload.InitApi(
            target_id=f'U_1_{dir_id}',
            file_name=save_name,
            file_io=data_io,
            helper=self._upload_helper
        ))
        token_result = None
        if not init_result['done']:
            token_result = self._client.execute_api(upload.TokenApi())
        return UploadTicket._create(init_result, token_result)
