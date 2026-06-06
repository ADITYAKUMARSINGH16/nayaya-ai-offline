import httpx
import tarfile
import io

class HTTPStreamProxy(io.RawIOBase):
    def __init__(self, url):
        self.client = httpx.Client()
        self.response = self.client.stream("GET", url)
        self.stream = self.response.__enter__()
        self.iterator = self.stream.iter_bytes(chunk_size=8192)
        self.buffer = b""

    def readinto(self, b):
        if not self.buffer:
            try:
                self.buffer = next(self.iterator)
            except StopIteration:
                return 0
        
        length = min(len(b), len(self.buffer))
        b[:length] = self.buffer[:length]
        self.buffer = self.buffer[length:]
        return length

    def close(self):
        self.response.__exit__(None, None, None)
        self.client.close()
        super().close()

def find_pdf():
    url = "https://indian-supreme-court-judgments.s3.amazonaws.com/data/tar/year=1996/english/english.tar"
    member_name = "1996_3_868_869.pdf"
    
    proxy = HTTPStreamProxy(url)
    try:
        with tarfile.open(fileobj=proxy, mode="r|") as tar:
            for member in tar:
                if member.name == member_name:
                    print(f"Found {member.name}, size: {member.size}")
                    return True
    except Exception as e:
        print(e)
    finally:
        proxy.close()
    return False

if __name__ == "__main__":
    find_pdf()
