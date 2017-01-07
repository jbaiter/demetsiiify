(function($){
  $.DemetsiiifyEndpoint = function(options) {

    jQuery.extend(this, {
      token:     null,
      uri:      null,
      url:      options.url,
      dfd:       null,
      annotationsList: [],
      idMapper: {}
    }, options);

    this.init();
  };

  $.DemetsiiifyEndpoint.prototype = {
    init: function() {
      // NOP
    },

    search: function(options, successCallback, errorCallback) {
      var _this = this;

      this.annotationsList = [];
      jQuery.ajax({
        url: "/iiif/annotation",
        type: 'GET',
        dataType: 'json',
        data: {
          q: options.uri,
          limit: 10000
        },
        success: function(data) {
          if (typeof successCallback === "function") {
            successCallback(data);
          } else {
            data.resources.forEach(function(a) {
              a.endpoint = _this;
            });
            _this.annotationsList = data.resources;
            _this.dfd.resolve(false);
          }
        },
        error: function() {
          if (typeof errorCallback === "function") {
            errorCallback();
          } else {
            console.log("The request for annotations has caused an error for endpoint: "+ options.uri);
          }
        }
      });
    },

    deleteAnnotation: function(annotationID, returnSuccess, returnError) {
      jQuery.ajax({
        url: annotationID,
        type: 'DELETE',
        dataType: 'json',
        success: function(data) {
          returnSuccess();
        },
        error: function() {
          returnError();
        }

      });
    },

    update: function(annotation, returnSuccess, returnError) {
      var this_ = this;
      delete annotation.endpoint;
      jQuery.ajax({
        url: annotation['@id'],
        type: 'PUT',
        dataType: 'json',
        data: JSON.stringify(annotation),
        contentType: "application/json; charset=utf-8",
        success: function(data) {
          data.endpoint = this_;
          returnSuccess(data);
        },
        error: function() {
          returnError();
        }
      });
      annotation.endpoint = this;
    },

    create: function(annotation, returnSuccess, returnError) {
      var _this = this;
      jQuery.ajax({
        url: '/iiif/annotation',
        type: 'POST',
        dataType: 'json',
        data: JSON.stringify(annotation),
        contentType: "application/json; charset=utf-8",
        success: function(data) {
          data.endpoint = _this;
          returnSuccess(data);
        },
        error: function() {
          returnError();
        }
      });
    },

    set: function(prop, value, options) {
      if (options) {
        this[options.parent][prop] = value;
      } else {
        this[prop] = value;
      }
    },
    userAuthorize: function(action, annotation) {
      return true; // allow all
    }
  };
}(Mirador));
