<?xml version="1.0" encoding="UTF-8"?>
<!--
Retourne systematiquement un warning, en plus du XML d'input.
-->

<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:gmd="http://www.isotc211.org/2005/gmd">

  <xsl:template match="/">
    <xsl:message terminate="no">Hello world 1</xsl:message>
    <xsl:message terminate="no">Un message un peu plus long, avec des détails.</xsl:message>
    <xsl:apply-templates select="@*|node()"/>
  </xsl:template>

  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>

</xsl:stylesheet>
