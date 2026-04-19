"""
Tests for semantic_validator module
"""

import pytest
from semantic_validator import SemanticValidator, ValidationResult


@pytest.fixture
def validator():
    """Create a validator instance for testing"""
    return SemanticValidator()


class TestSearchValidation:
    """Tests for search tool validation"""
    
    def test_valid_search_call(self, validator):
        """Test valid search call"""
        result = validator.validate(
            tool_name="search",
            arguments={"query": "AI safety"}
        )
        assert result.is_valid
        assert result.errors is None
    
    def test_missing_required_query(self, validator):
        """Test search without required query field"""
        result = validator.validate(
            tool_name="search",
            arguments={"max_results": 5}
        )
        assert not result.is_valid
        assert result.errors is not None
        assert len(result.errors) > 0
        assert result.corrective_guidance is not None
    
    def test_empty_query_rejected(self, validator):
        """Test that empty query is rejected"""
        result = validator.validate(
            tool_name="search",
            arguments={"query": "", "max_results": 5}
        )
        assert not result.is_valid
    
    def test_query_max_length(self, validator):
        """Test query length validation"""
        long_query = "a" * 1000  # Exceeds max
        result = validator.validate(
            tool_name="search",
            arguments={"query": long_query}
        )
        assert not result.is_valid
    
    def test_max_results_constraint(self, validator):
        """Test max_results bounds"""
        result = validator.validate(
            tool_name="search",
            arguments={"query": "test", "max_results": 200}  # Exceeds max of 100
        )
        assert not result.is_valid


class TestFetchDocumentValidation:
    """Tests for fetch_document tool validation"""
    
    def test_valid_fetch_document(self, validator):
        """Test valid document fetch"""
        result = validator.validate(
            tool_name="fetch_document",
            arguments={
                "document_id": "doc-123",
                "format": "pdf"
            }
        )
        assert result.is_valid
    
    def test_invalid_format(self, validator):
        """Test invalid document format"""
        result = validator.validate(
            tool_name="fetch_document",
            arguments={
                "document_id": "doc-123",
                "format": "xml"  # Not in allowed formats
            }
        )
        assert not result.is_valid
    
    def test_too_many_pages(self, validator):
        """Test requesting too many pages"""
        result = validator.validate(
            tool_name="fetch_document",
            arguments={
                "document_id": "doc-123",
                "pages": list(range(150))  # More than 100
            }
        )
        assert not result.is_valid


class TestValidationStatistics:
    """Tests for validation statistics tracking"""
    
    def test_stats_tracking(self, validator):
        """Test that statistics are properly tracked"""
        # Make multiple validations
        validator.validate("search", {"query": "test"})  # Pass
        validator.validate("search", {"max_results": 5})  # Fail
        validator.validate("search", {"query": "another"})  # Pass
        
        stats = validator.get_stats()
        assert stats["total_validations"] == 3
        assert stats["passed"] == 2
        assert stats["failed"] == 1
    
    def test_success_rate(self, validator):
        """Test success rate calculation"""
        validator.validate("search", {"query": "test"})
        validator.validate("search", {"query": "test 2"})
        
        stats = validator.get_stats()
        assert "success_rate" in stats
        assert "100.0" in stats["success_rate"]


class TestSchemaInfo:
    """Tests for schema information retrieval"""
    
    def test_get_schema_info(self, validator):
        """Test retrieving schema information"""
        info = validator.get_schema_info("search")
        assert info["tool_name"] == "search"
        assert "fields" in info
        assert "query" in info["fields"]
        assert info["fields"]["query"]["required"] == True
    
    def test_unknown_tool_schema(self, validator):
        """Test retrieving schema for unknown tool"""
        info = validator.get_schema_info("unknown_tool")
        assert "error" in info


class TestGuidanceGeneration:
    """Tests for corrective guidance generation"""
    
    def test_guidance_is_helpful(self, validator):
        """Test that corrective guidance is generated"""
        result = validator.validate(
            tool_name="search",
            arguments={"max_results": 5}  # Missing query
        )
        assert result.corrective_guidance is not None
        assert "query" in result.corrective_guidance.lower()
        assert "required" in result.corrective_guidance.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
