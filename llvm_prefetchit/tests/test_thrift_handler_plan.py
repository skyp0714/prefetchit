import importlib.util
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from thrift_handler_prefetch_plan import handler_edges


def test_handler_edges_require_unique_matching_namespace_and_service():
    symbols={'p':'media::MovieIdServiceProcessor::process_Upload(int, Protocol*)',
             'h':'media::MovieIdHandler::Upload(long, std::string const&)',
             'foreign':'other::MovieIdHandler::Upload(long)',
             'wrong':'media::RatingHandler::Upload(long)',
             'unused':'media::MovieIdHandler::Register(long)'}
    assert handler_edges(symbols)=={'p':'h'}
    symbols['overload']='media::MovieIdHandler::Upload(int)'
    assert handler_edges(symbols)=={}
