<?xml version="1.0" encoding="UTF-8"?>
<!--
Change les métadonnées de langue du record.
-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:gco="http://www.isotc211.org/2005/gco"
                xmlns:gmd="http://www.isotc211.org/2005/gmd"
                exclude-result-prefixes="#all">
  <xsl:strip-space elements="*"/>

  <xsl:param name="language" select="'eng'"/>

  <!-- Match and replace text in gco:CharacterString -->
  <xsl:template match="/gmd:MD_Metadata/gmd:language/gco:CharacterString/text()">
      <xsl:value-of select="$language"/>
  </xsl:template>

  <!-- Match and replace gmd:LanguageCode -->
  <xsl:template match="/gmd:MD_Metadata/gmd:language/gmd:LanguageCode">
      <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="{$language}"/>
  </xsl:template>

  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>
</xsl:stylesheet>
