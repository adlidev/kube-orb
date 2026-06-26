Feature: Wizard string configuration
  As a user setting up a kube-illume session
  I want to configure filter, highlight, and monitor strings
  So that I can refine my log view from the start

  Background:
    Given the saved strings file contains filters ["DEBUG", "health"]

  Scenario: User loads saved filters and adds a new one
    Given I am on the filters wizard step
    When I check "DEBUG" from the saved list
    And I enter "timeout" in the new strings input
    And I click Next
    Then the active filters should be ["DEBUG", "timeout"]

  Scenario: User adds a new regex filter
    Given I am on the filters wizard step
    When I enter "/5[0-9]{2}/" in the new strings input
    And I click Next
    Then the active filters should be ["/5[0-9]{2}/"]

  Scenario: User opts to save new strings to the global list
    Given I am on the filters wizard step
    When I enter "ERROR" in the new strings input
    And "Save new strings to list" is checked
    And I click Next
    Then "ERROR" should be added to the saved filters list

  Scenario: User opts NOT to save new strings
    Given I am on the filters wizard step
    When I enter "ERROR" in the new strings input
    And "Save new strings to list" is unchecked
    And I click Next
    Then "ERROR" should NOT be in the saved filters list
    And the active filters should be ["ERROR"]

  Scenario: User clears all saved string selections
    Given I am on the filters wizard step
    When I click "Clear all"
    And I click Next
    Then the active filters should be []
